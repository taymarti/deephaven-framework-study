"""
Probe the framework's extension points and replay, on an embedded pip server
(no client). Run with the server venv on native Windows or Linux:
  .venv-server/Scripts/python tests/probe_framework_constructs.py
Results go to tests/probe_framework_constructs.json.

  1. Java UDF: our own compiled class on the classpath, called from a formula
  2. Python UDF: a type-hinted Python function called from a formula
  3. function_generated_table: a custom source that re-runs our function
  4. ring_table: a bounded window over a ticking table
  5. keyed input_table: client-style writes (add, then delete)
  6. TableReplayer: history replayed on a simulated clock through UNCHANGED graph code
  7. Event-driven backtest: the same graph code stepped through history by our own loop
"""
import json
import os
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "probe_framework_constructs.json"
R: dict = {}


def jvm_args() -> list:
    args = ["-Xmx1g", "-DAuthHandlers=io.deephaven.auth.AnonymousAuthenticationHandler"]
    if os.name == "nt":  # same workarounds as server/run_server.py
        jh = pathlib.Path(os.environ["JAVA_HOME"])
        for d in (jh / "bin", jh / "bin" / "server"):
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"
            os.add_dll_directory(str(d))
        args += ["-Dweb.storage.layout.directory=layouts", "-Dweb.storage.notebook.directory=notebooks"]
    return args


def compile_java() -> str:
    out = ROOT / "java_out"
    javac = pathlib.Path(os.environ["JAVA_HOME"]) / "bin" / ("javac.exe" if os.name == "nt" else "javac")
    subprocess.run([str(javac), "-d", str(out), str(ROOT / "java" / "com" / "acme" / "Risk.java")], check=True)
    import zipfile
    jar = ROOT / "acme-risk.jar"  # a plain jar of our class, like any third-party library
    with zipfile.ZipFile(jar, "w") as z:
        z.write(out / "com" / "acme" / "Risk.class", "com/acme/Risk.class")
    return str(jar)


def check(name, fn):
    try:
        R[name] = fn()
    except Exception as e:  # noqa: BLE001
        R[name + "_full"] = str(e)[:6000]
        R[name] = "FAIL: " +" | ".join(str(e).splitlines()[:6])[:900]
    print(name, "->", R[name], flush=True)


# The graph code under test: written once, used live, under replay and in a backtest.
def build_graph(trades):
    from deephaven import agg
    return trades.agg_by([agg.count_("N"), agg.sum_("Qty")], by="Sym")


def main() -> None:
    from deephaven_server import Server
    Server(port=int(os.environ.get("DH_PORT", "10003")), jvm_args=jvm_args(), extra_classpath=[compile_java()]).start()

    from deephaven import empty_table, function_generated_table, input_table, new_table, ring_table, time_table
    from deephaven import dtypes as dht
    from deephaven import query_library
    from deephaven.column import long_col, string_col
    from deephaven.replay import TableReplayer
    from deephaven.table_listener import listen
    from deephaven.pandas import to_pandas

    def java_udf():
        import jpy
        cp = str(jpy.get_type("java.lang.System").getProperty("java.class.path"))
        R["1a_classpath_has_jar"] = "acme-risk.jar" in cp
        import zipfile
        R["1a_jar_entries"] = zipfile.ZipFile(ROOT / "acme-risk.jar").namelist()
        for how, f in (("jpy.get_type", lambda: jpy.get_type("com.acme.Risk")),
                       ("system_loader", lambda: jpy.get_type("java.lang.ClassLoader").getSystemClassLoader().loadClass("com.acme.Risk"))):
            try:
                f()
                R["1b_load_" + how] = "ok"
            except Exception as e:  # noqa: BLE001
                R["1b_load_" + how] = str(e).splitlines()[0][:200]
        query_library.import_static("com.acme.Risk")
        t = new_table([long_col("Qty", [100, -50]), long_col("Px100", [9950, 10120])]) \
            .update(["Px = Px100 / 100.0", "Dur = 7.5", "Dv01 = dv01(Qty, Px, Dur)"])
        return to_pandas(t)[["Qty", "Px", "Dv01"]].to_dict("records")
    check("1_java_udf_in_formula", java_udf)

    import numpy as np
    global pnl_int, pnl_np, pnl_none

    def pnl_int(qty: int, px: float, mark: float) -> float:
        return qty * (mark - px)

    def pnl_np(qty: np.int64, px: np.float64, mark: np.float64) -> np.float64:
        return qty * (mark - px)

    def pnl_none(qty, px, mark):
        return qty * (mark - px)

    global pnl_float

    def pnl_float(qty: float, px: float, mark: float) -> float:
        return qty * (mark - px)

    for fn, arg in (("pnl_int", "Qty"), ("pnl_np", "Qty"), ("pnl_none", "Qty"), ("pnl_float", "(double) Qty")):
        def run(fn=fn, arg=arg):
            t = new_table([long_col("Qty", [100, -50])]).update(["Px = 99.5", "Mark = 100.0", f"PnL = {fn}({arg}, Px, Mark)"])
            return {"values": to_pandas(t)["PnL"].tolist(), "column_type": str(t.columns[-1].data_type)}
        check(f"2_python_udf_{fn}", run)

    def java_fqn():  # skip the query library: fully qualified name in the formula
        t = new_table([long_col("Qty", [100, -50])]).update(["Px = 99.5", "Dv01 = com.acme.Risk.dv01(Qty, Px, 7.5)"])
        return to_pandas(t)["Dv01"].tolist()
    check("1c_java_fully_qualified_in_formula", java_fqn)

    def java_ctx_import():  # import through the execution context's query library, by Class object
        import jpy
        from deephaven.execution_context import get_exec_ctx
        get_exec_ctx().j_exec_ctx.getQueryLibrary().importStatic(jpy.get_type("com.acme.Risk").jclass)
        t = new_table([long_col("Qty", [100, -50])]).update(["Px = 99.5", "Dv01 = dv01(Qty, Px, 7.5)"])
        return to_pandas(t)["Dv01"].tolist()
    check("1d_java_import_static_via_class_object", java_ctx_import)

    def fgt():
        calls = {"n": 0}

        def snapshot():
            calls["n"] += 1
            return new_table([string_col("Source", ["my_feed"]), long_col("Calls", [calls["n"]])])
        t = function_generated_table(snapshot, refresh_interval_ms=200)
        time.sleep(1.5)
        return {"function_calls_in_1.5s": calls["n"], "table_value": int(to_pandas(t)["Calls"][0])}
    check("3_function_generated_table", fgt)

    def ring():
        r = ring_table(time_table("PT0.1s"), capacity=5)
        time.sleep(3.0)
        return {"rows_after_3s_at_10_per_s": r.size}
    check("4_ring_table", ring)

    def inp():
        t = input_table({"Desk": dht.string, "Limit": dht.double}, key_cols="Desk")
        t.add(new_table([string_col("Desk", ["Rates", "FX"])]).update("Limit = 1e6"))
        t.add(new_table([string_col("Desk", ["Rates"])]).update("Limit = 2e6"))  # upsert by key
        time.sleep(1.2)
        after_add = to_pandas(t).sort_values("Desk").to_dict("records")
        t.delete(new_table([string_col("Desk", ["FX"])]))
        time.sleep(1.2)
        return {"after_add_and_upsert": after_add, "rows_after_delete": t.size}
    check("5_keyed_input_table", inp)

    def replay():
        global T0
        T0 = time.time_ns() - 3_600_000_000_000  # history from an hour ago, 20 rows 200 ms apart
        hist = empty_table(20).update(["Timestamp = epochNanosToInstant(T0 + ii * 200_000_000L)",
                                       "Sym = ii % 2 == 0 ? `AAPL` : `MSFT`", "Qty = (long) (ii + 1)"])
        rp = TableReplayer(T0, T0 + 5_000_000_000)
        trades = rp.add_table(hist, "Timestamp")
        live_view = build_graph(trades)  # unchanged graph code
        stamped = trades.update("SeenAtNow = now()")
        rp.start()
        t_start, samples = time.time(), []
        for _ in range(6):
            time.sleep(1.0)
            samples.append(trades.size)
        last = to_pandas(stamped.tail(1))
        lag_hours = (time.time_ns() - last["SeenAtNow"].astype("int64").iloc[0]) / 3.6e12
        out = {"replayed_rows_each_second": samples, "wall_seconds": round(time.time() - t_start, 1),
               "graph_result": to_pandas(live_view).to_dict("records"),
               "now()_in_formula_is_replay_time": abs(lag_hours - 1) < 0.1, "now()_hours_behind_wall": round(lag_hours, 3)}
        rp.shutdown()
        return out
    check("6_table_replayer", replay)

    def backtest():
        import jpy
        from deephaven.execution_context import ExecutionContext, get_exec_ctx
        from deephaven.stream.table_publisher import table_publisher
        from deephaven.update_graph import UpdateGraph
        edug = jpy.get_type("io.deephaven.engine.updategraph.impl.EventDrivenUpdateGraph")
        ug = edug.newBuilder("backtest_clock").build()
        ctx = ExecutionContext(j_exec_ctx=get_exec_ctx().j_exec_ctx.withUpdateGraph(ug))
        seen = []
        with ctx:
            feed, pub = table_publisher("hist_feed", {"Sym": dht.string, "Qty": dht.int64},
                                        update_graph=UpdateGraph(j_update_graph=ug))
            from deephaven.stream import blink_to_append_only
            result = build_graph(blink_to_append_only(feed))  # same graph code as live and replay
            h = listen(result, lambda u, r: seen.append(ug.clock().currentStep()))
            t0, sync = time.perf_counter(), 0
            for i in range(200):  # 200 historical slices, as fast as the engine can take them
                pub.add(new_table([string_col("Sym", ["AAPL" if i % 2 else "MSFT"]), long_col("Qty", [i + 1])]))
                before = ug.clock().currentStep()
                ug.requestRefresh()
                if ug.clock().currentStep() > before:
                    sync += 1
            elapsed = time.perf_counter() - t0
            time.sleep(0.5)
            h.stop()
        return {"slices": 200, "seconds": round(elapsed, 3), "callbacks": len(seen),
                "requestRefresh_returned_after_step": f"{sync}/200",
                "result": to_pandas(result).to_dict("records")}
    check("7_event_driven_backtest", backtest)

    OUT.write_text(json.dumps(R, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    os._exit(0)


if __name__ == "__main__":
    main()


