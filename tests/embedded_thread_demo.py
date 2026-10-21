"""
Can Deephaven run as a THREAD-hosted service inside our framework's process,
instead of a subprocess?

The host's main thread runs an asyncio loop (standing in for our EventManager).
A background thread starts the embedded server. We then measure:
  1. startup off the main thread, while the loop keeps running
  2. in-process table use from the main thread (no client, no network)
  3. an in-process listener bridged into asyncio
  4. GIL contention: listener lateness while the host burns CPU in Python
  5. what the console scope is (are the host's globals visible to clients?)
  6. whether a second Server can start in the same process
Results go to tests/embedded_thread_result.json. Run with the server venv:
  .venv-server/Scripts/python tests/embedded_thread_demo.py
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import statistics
import sys
import threading
import time

OUT = pathlib.Path(__file__).with_name("embedded_thread_result.json")
PORT = int(os.environ.get("DH_PORT", "10002"))
R: dict = {"python": sys.version.split()[0]}
HOST_STATE = {"note": "this dict lives in the host's __main__"}  # framework state


def jvm_args() -> list:
    args = ["-Xmx1g", "-DAuthHandlers=io.deephaven.auth.AnonymousAuthenticationHandler"]
    if os.name == "nt":  # same workarounds as server/run_server.py
        jh = pathlib.Path(os.environ["JAVA_HOME"])
        for d in (jh / "bin", jh / "bin" / "server"):
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"
            os.add_dll_directory(str(d))
        args += ["-Dweb.storage.layout.directory=layouts", "-Dweb.storage.notebook.directory=notebooks"]
    return args


ready = threading.Event()
SERVER_CTX: dict = {}


def run_deephaven() -> None:
    t0 = time.perf_counter()
    try:
        from deephaven_server import Server
        server = Server(port=PORT, jvm_args=jvm_args())
        server.start()
        R["1_started_on_thread"] = threading.current_thread().name
        R["1_start_seconds"] = round(time.perf_counter() - t0, 1)
        # The thread that started the server holds the systemic execution context.
        from deephaven.execution_context import get_exec_ctx
        SERVER_CTX["ctx"] = get_exec_ctx()
    except Exception as e:  # noqa: BLE001
        R["1_start_error"] = repr(e)[:300]
    ready.set()


async def main() -> None:
    th = threading.Thread(target=run_deephaven, name="dh-service", daemon=True)
    th.start()
    loop_ticks = 0
    while not ready.is_set():  # our event loop keeps running during startup
        await asyncio.sleep(0.05)
        loop_ticks += 1
    R["1_host_loop_ticks_during_startup"] = loop_ticks
    if "1_start_error" in R:
        return

    from deephaven import agg, time_table
    from deephaven.execution_context import get_exec_ctx
    from deephaven.table_listener import listen

    # 2. In-process use from the MAIN thread: is an execution context needed?
    try:
        time_table("PT1s")
        R["2_table_op_on_main_thread_without_ctx"] = "ok"
    except Exception as e:  # noqa: BLE001
        R["2_table_op_on_main_thread_without_ctx"] = "FAIL: " + str(e).splitlines()[0][:160]
    try:
        with get_exec_ctx():  # the MAIN thread's own context
            time_table("PT1s")
        R["2_with_main_thread_get_exec_ctx"] = "ok"
    except Exception as e:  # noqa: BLE001
        R["2_with_main_thread_get_exec_ctx"] = "FAIL: " + str(e).splitlines()[0][:160]
    ctx = SERVER_CTX["ctx"]  # the context captured on the thread that started the server
    with ctx:
        ticks = time_table("PT0.1s").update(["Sym = (ii % 2 == 0) ? `A` : `B`", "Px = 100 + Math.sin(ii / 10.0)"])
        summary = ticks.agg_by([agg.count_("N")], by="Sym")
    globals()["embedded_ticks"], globals()["embedded_summary"] = ticks, summary

    # 3. In-process listener -> asyncio, via call_soon_threadsafe.
    loop = asyncio.get_running_loop()
    lags_ms: list = []
    queue: asyncio.Queue = asyncio.Queue()

    def on_update(update, is_replay):
        now_ns = time.time_ns()
        added = update.added()
        if "Timestamp" in added and len(added["Timestamp"]):
            ts = added["Timestamp"][-1].astype("datetime64[ns]").astype("int64")
            lags_ms.append((now_ns - int(ts)) / 1e6)
        loop.call_soon_threadsafe(queue.put_nowait, len(added.get("Sym", [])))

    with ctx:
        handle = listen(ticks, on_update)
    got = 0
    t_end = time.time() + 4
    while time.time() < t_end:
        try:
            got += await asyncio.wait_for(queue.get(), timeout=1)
        except asyncio.TimeoutError:
            pass
    R["3_rows_seen_by_asyncio_in_4s"] = got
    idle = list(lags_ms)
    lags_ms.clear()

    # 4. GIL contention: burn CPU in pure Python on the main thread for 4 s.
    def burn(seconds: float) -> None:
        stop = time.perf_counter() + seconds
        x = 0
        while time.perf_counter() < stop:
            x += 1
    burn(4)
    await asyncio.sleep(1.5)  # let queued callbacks drain
    busy = list(lags_ms)
    R["4_listener_lag_ms_idle_median"] = round(statistics.median(idle), 1) if idle else None
    R["4_listener_lag_ms_idle_max"] = round(max(idle), 1) if idle else None
    R["4_listener_lag_ms_host_busy_median"] = round(statistics.median(busy), 1) if busy else None
    R["4_listener_lag_ms_host_busy_max"] = round(max(busy), 1) if busy else None
    R["4_callbacks_idle_vs_busy"] = [len(idle), len(busy)]

    # 5. Console scope: run_script from a client sees the host's __main__ globals?
    #    (Checked by the companion client step; we publish a marker here.)
    import __main__
    R["5_host_main_is_console_scope_candidate"] = "HOST_STATE" in vars(__main__)
    OUT.write_text(json.dumps(R, indent=2), encoding="utf-8")  # partial results for the client step
    marker = OUT.with_suffix(".ready")
    marker.write_text("ready", encoding="utf-8")
    t_wait = time.time() + 60
    while time.time() < t_wait and not OUT.with_suffix(".client").exists():
        await asyncio.sleep(0.5)
    if OUT.with_suffix(".client").exists():
        R["5_client_view"] = json.loads(OUT.with_suffix(".client").read_text(encoding="utf-8"))
    R["5_host_state_after_client"] = dict(HOST_STATE)

    # 6. A second Server in the same process?
    try:
        from deephaven_server import Server
        Server(port=PORT + 1, jvm_args=jvm_args()).start()
        R["6_second_server_same_process"] = "started (unexpected)"
    except Exception as e:  # noqa: BLE001
        R["6_second_server_same_process"] = "FAIL: " + str(e).splitlines()[0][:200]

    handle.stop()
    R["7_main_returning_at"] = time.strftime("%H:%M:%S")


if __name__ == "__main__":
    for p in (OUT, OUT.with_suffix(".ready"), OUT.with_suffix(".client")):
        p.unlink(missing_ok=True)
    asyncio.run(main())
    OUT.write_text(json.dumps(R, indent=2), encoding="utf-8")
    print(json.dumps(R, indent=2), flush=True)
