"""Where the bundled, non-Python artifacts live: inside the installed wheel, or (when running from
the source tree, e.g. an editable install) in the units' own build folders (java/target, web/dist)."""
from importlib.resources import files
from pathlib import Path

_BUNDLE = Path(str(files("dh_desk") / "_bundle"))
_PROJECT = Path(__file__).resolve().parents[2]  # desk-app/, from src/dh_desk/resources.py


def java_jar() -> Path:
    """The Java unit's jar (Pricing, LimitBreachTracker)."""
    return _first(_BUNDLE / "java" / "dh-desk.jar", _PROJECT / "java" / "target" / "dh-desk.jar")


def web_root() -> Path:
    """The web unit's build (index.html + assets/)."""
    return _first(_BUNDLE / "web", _PROJECT / "web" / "dist")


def _first(*candidates: Path) -> Path:
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"none of {[str(c) for c in candidates]} exists: build first (pixi run desk-app-build)")
