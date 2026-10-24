# Application-mode shim: load the Python entry module from hybrid/src/main/python (run from the repo root).
import pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd() / "hybrid" / "src" / "main" / "python"))
from hybrid_py import hy_trades, hy_signals, hy_flips, _hy_tracker  # noqa: F401  (published as fields)
