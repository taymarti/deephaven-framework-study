"""Probe: server executors and a second, event-driven update graph (run via run_script)."""
import time

import jpy
from deephaven import new_table
from deephaven.column import string_col
from deephaven.server import executors

_rows = [("executor names", str(list(executors.executor_names())))]

# A task on the "concurrent" executor: a JVM thread, given work from Python.
_done = []
executors.submit_task("concurrent", lambda: _done.append(time.time()))
time.sleep(0.5)
_rows.append(("submit_task(concurrent) ran", str(bool(_done))))

# A second update graph that only advances when told to (event-driven).
try:
    _EDUG = jpy.get_type("io.deephaven.engine.updategraph.impl.EventDrivenUpdateGraph")
    _ug2 = _EDUG.newBuilder("probe_event_driven").build()
    _rows.append(("EventDrivenUpdateGraph built", f"{_ug2.getName()} ({_ug2.getClass().getSimpleName()})"))
    _step0 = _ug2.clock().currentStep()
    _ug2.requestRefresh()  # one explicit cycle
    time.sleep(0.5)
    _rows.append(("requestRefresh advanced its clock", f"{_step0} -> {_ug2.clock().currentStep()}"))
except Exception as e:  # noqa: BLE001
    _rows.append(("EventDrivenUpdateGraph", f"FAIL: {str(e).splitlines()[0][:150]}"))

probe_runtime = new_table([string_col("Check", [r[0] for r in _rows]), string_col("Result", [r[1] for r in _rows])])
