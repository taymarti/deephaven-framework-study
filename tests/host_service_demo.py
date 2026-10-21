"""
Our framework hosting Deephaven as a service (the "inverted" pattern):

  host process (asyncio main loop, our clock, our worker pool)
      |-- starts server/run_server.py as a SUBPROCESS on its own port
      |-- talks to it only as a client (pydeephaven)
      |-- stops it at shutdown

  python tests/host_service_demo.py --server-python .venv-server/Scripts/python.exe
(JAVA_HOME must point at Java 17+.)
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures as cf
import math
import pathlib
import subprocess
import sys
import time

from pydeephaven import Session

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeephavenService:
    """Start the server as a subprocess, connect as a client, stop it at shutdown."""

    def __init__(self, server_python: str, port: int, app_dir: str | None = None):
        self.server_python, self.port, self.app_dir = server_python, port, app_dir
        self.proc: subprocess.Popen | None = None
        self.session: Session | None = None

    def start(self, timeout: float = 180) -> "DeephavenService":
        cmd = [self.server_python, str(ROOT / "server" / "run_server.py"), "--port", str(self.port)]
        cmd += ["--app-dir", self.app_dir] if self.app_dir else ["--no-app"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        while True:  # the port opens only after startup (and app-mode scripts) finish
            try:
                self.session = Session(host="localhost", port=self.port, auth_type="Anonymous")
                return self
            except Exception:  # noqa: BLE001
                if self.proc.poll() is not None or time.time() > deadline:
                    raise RuntimeError(f"Deephaven did not come up (exit={self.proc.poll()})")
                time.sleep(2)

    def stop(self) -> None:
        if self.session:
            self.session.close()  # releases this client's tickets
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def arbitrary_work(n: int) -> float:
    """Non-Deephaven work in a separate process, just for fun."""
    return sum(math.sin(i) ** 2 for i in range(n))


class Algorithm:
    def __init__(self, dh: DeephavenService, pool: cf.ProcessPoolExecutor):
        self.dh, self.pool, self.log = dh, pool, []

    async def on_initialize(self) -> None:
        # Deploy server-side logic: a ticking feed and a live aggregate, built once.
        self.dh.session.run_script(
            "from deephaven import time_table, agg\n"
            "ticks = time_table('PT0.1s').update(['Sym = (ii % 2 == 0) ? `A` : `B`', 'Px = 100 + Math.sin(ii / 10.0)'])\n"
            "summary = ticks.agg_by([agg.count_('N'), agg.avg('AvgPx = Px')], by='Sym')\n"
        )
        self.summary = self.dh.session.open_table("summary")  # a handle; the server keeps it live

    async def on_checkpoint(self, k: int) -> None:
        # OUR clock decides when to look; Deephaven has kept `summary` current meanwhile.
        df = self.summary.to_arrow().to_pandas()  # a fresh snapshot of the live table
        fut = asyncio.get_running_loop().run_in_executor(self.pool, arbitrary_work, 200_000)
        side = await fut
        self.log.append((k, df.set_index("Sym")["N"].to_dict(), round(side, 1)))

    async def on_shutdown(self) -> None:
        self.summary.close()


async def main(server_python: str, port: int) -> None:
    t0 = time.time()
    dh = DeephavenService(server_python, port).start()
    print(f"server subprocess up in {time.time() - t0:.1f}s (pid {dh.proc.pid})", flush=True)
    with cf.ProcessPoolExecutor(max_workers=2) as pool:
        algo = Algorithm(dh, pool)
        try:
            await algo.on_initialize()
            for k in range(3):  # three checkpoints on our own 1.5 s clock
                await asyncio.sleep(1.5)
                await algo.on_checkpoint(k)
            for row in algo.log:
                print("checkpoint", row)
            await algo.on_shutdown()
        finally:
            dh.stop()
    print(f"server subprocess exit code: {dh.proc.returncode}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-python", default=sys.executable)
    ap.add_argument("--port", type=int, default=10001)
    a = ap.parse_args()
    asyncio.run(main(a.server_python, a.port))
