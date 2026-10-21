"""Which runtime are we in, and the small context facts that differ between them."""
import datetime as _dt
import getpass
import importlib.util
import os
from functools import lru_cache

# Version the plant runs. Code tested locally on another Core version can still
# differ (APIs, defaults); runtime() warns when the local version differs.
PLANT_CORE_VERSION = os.environ.get("DHFW_PLANT_CORE_VERSION", "")


@lru_cache(maxsize=1)
def is_enterprise() -> bool:
    """True inside an Enterprise Core+ worker. DHFW_RUNTIME=community|enterprise overrides detection."""
    forced = os.environ.get("DHFW_RUNTIME", "").lower()
    if forced in ("community", "enterprise"):
        return forced == "enterprise"
    return importlib.util.find_spec("deephaven_enterprise") is not None


def runtime() -> dict:
    """A small report for logs and dashboards: which runtime, versions, and mode."""
    import deephaven
    info = {"runtime": "enterprise" if is_enterprise() else "community",
            "core_version": deephaven.__version__, "replay_date": os.environ.get("DHFW_REPLAY_DATE")}
    if PLANT_CORE_VERSION and PLANT_CORE_VERSION != deephaven.__version__:
        info["warning"] = f"local Core {deephaven.__version__} != plant Core {PLANT_CORE_VERSION}"
    return info


def today() -> str:
    """The business date as 'YYYY-MM-DD'.

    Enterprise: the engine's today(), which a replay query moves to its replay date.
    Community: DHFW_REPLAY_DATE when set (replay mode), else the local calendar date.
    Use this in Python instead of hard-coded dates so replay needs no code change.
    """
    if is_enterprise():
        from deephaven.time import dh_today
        return dh_today()
    return os.environ.get("DHFW_REPLAY_DATE") or _dt.date.today().isoformat()


def effective_user() -> str:
    """Enterprise: the effective user from auth_context. Community: DHFW_USER or the OS user."""
    if is_enterprise():
        # Function name not confirmed against a Core+ worker; verify on the plant.
        from deephaven_enterprise import auth_context
        fn = getattr(auth_context, "get_effective_user", None) or getattr(auth_context, "effective_user")
        return str(fn())
    return os.environ.get("DHFW_USER") or getpass.getuser()
