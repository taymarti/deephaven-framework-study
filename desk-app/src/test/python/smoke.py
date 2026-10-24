"""
Deploy the built wheel exactly as a user would, then test it end to end:

  1. a fresh virtual environment (uv venv)
  2. pip-install target/dist/dh_desk-*.whl into it (its dependencies come from PyPI)
  3. run the two entry points: dh-desk-server, then dh-desk-web
  4. run smoke_check.py against them (tables, Java pricing, breach -> alert flow, web + proxy)

    pixi run desk-app-smoke        (or: python src/test/python/smoke.py, with uv and a JDK available)
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]  # desk-app/
VENV = PROJECT / "target" / "smoke-venv"
WIN = os.name == "nt"
SERVER_PORT, WEB_PORT = 10020, 4020


def run(cmd) -> None:
    print("$", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True)


def wait_for(proc: subprocess.Popen, marker: str, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            print("  |", line.rstrip(), flush=True)
        if marker in line:
            # keep draining, or a chatty process (the server logs a lot) blocks once the pipe fills
            threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
            return
        if proc.poll() is not None:
            sys.exit(f"exited ({proc.returncode}) before printing {marker!r}")
    sys.exit(f"timed out waiting for {marker!r}")


def main() -> None:
    if not os.environ.get("JAVA_HOME"):
        sys.exit("JAVA_HOME must point to a JDK 17+ (pixi's environment sets it)")
    wheel = next((PROJECT / "target" / "dist").glob("dh_desk-*.whl"))
    shutil.rmtree(VENV, ignore_errors=True)
    run(["uv", "venv", "--python", f"{sys.version_info.major}.{sys.version_info.minor}", VENV])
    py = VENV / ("Scripts" if WIN else "bin") / ("python.exe" if WIN else "python")
    run(["uv", "pip", "install", "--python", py, f"{wheel}[test]"])
    bin_dir = py.parent
    procs = []
    try:
        server = subprocess.Popen([bin_dir / "dh-desk-server", "--port", str(SERVER_PORT)], cwd=VENV,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append(server)
        wait_for(server, "dh-desk is up", 300)
        web = subprocess.Popen([bin_dir / "dh-desk-web", "--port", str(WEB_PORT), "--dh-url",
                                f"http://localhost:{SERVER_PORT}"], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
        procs.append(web)
        wait_for(web, "dh-desk web", 60)
        run([py, PROJECT / "src" / "test" / "python" / "smoke_check.py",
             "--server-port", SERVER_PORT, "--web-port", WEB_PORT])
        print("SMOKE OK", flush=True)
    finally:
        for p in reversed(procs):
            p.terminate()


if __name__ == "__main__":
    main()
