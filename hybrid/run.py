"""
Build the Java half, then start Deephaven with the jar on the classpath and one of
two entry points. Run from the repo root with the server venv:

    python hybrid/run.py --entry python      # src/main/python/hybrid_py.py builds the graph, using Java nodes
    python hybrid/run.py --entry java        # a one-line loader calls com.acme.hybrid.HybridApp.start()

Both publish hy_trades, hy_signals and hy_flips (the Java entry adds hy_alerts); open the IDE at http://localhost:10000/ide/.
"""
import argparse
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build import build  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", choices=["python", "java"], required=True)
    ap.add_argument("--port", type=int, default=10000)
    args, rest = ap.parse_known_args()
    jar = build()
    cmd = [sys.executable, str(HERE.parent / "server" / "run_server.py"), "--port", str(args.port),
           "--app-dir", str(HERE / "src" / "main" / "resources" / "app.d" / args.entry), "--classpath", str(jar), *rest]
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
