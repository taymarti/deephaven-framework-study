"""
Probe: how do application-mode scripts relate to the console's global scope?

Defines one table each way and records what the script itself can see:
  probe_plain        plain top-level assignment (no `global`)
  probe_global       declared `global`
  _probe_underscore  declared `global`, underscore-prefixed (is it still a field?)
  probe_field        published only via ApplicationState under app id probe.scoping
"""
import __main__

from deephaven import empty_table, new_table, perfmon
from deephaven.appmode import get_app_state
from deephaven.column import bool_col, string_col

global perf_ancestors, probe_global, _probe_underscore
perf_ancestors = perfmon.update_performance_ancestors_log()  # graph ancestry from boot

probe_plain = empty_table(1).update("Src = `plain`")
probe_global = empty_table(1).update("Src = `global`")
_probe_underscore = empty_table(1).update("Src = `underscore`")

app = get_app_state()
app["probe_field"] = empty_table(1).update("Src = `app field`")

# What namespace is this script actually running in?
app["probe_env"] = new_table([
    string_col("Check", ["globals() is __main__ dict", "__name__", "probe_plain in globals()",
                         "app state repr"]),
    string_col("Value", [str(globals() is vars(__main__)), str(__name__),
                         str("probe_plain" in globals()), repr(app)[:120]]),
])
