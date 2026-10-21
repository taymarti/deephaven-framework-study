"""
Rung 1 - The script runs once; the graph runs forever.

Your EventManager.run() never returns: it IS the loop. A Deephaven script must
return. What keeps running afterwards is the table graph the script declared,
driven by the engine's update-graph clock (one "cycle" ~ every second).

Watch it:
  python examples/run.py examples/01_lifecycle.py --show ex1_ticks --every 2 --times 3
"""
import time

import jpy
from deephaven import time_table

_t0 = time.perf_counter()

# A source table. Creating it is all it takes - the engine refreshes it every
# cycle from now on. No thread, no loop, no "start feeds" phase.
ex1_ticks = time_table("PT0.5s").update([
    "Row = ii",
    # Evaluated when the row is added, i.e. during the update cycle that adds it.
    "SeenAt = now()",
    # The engine's logical clock: one step per update cycle. Several rows can
    # share a step - they arrived in the same cycle (a "checkpoint").
    "Step = io.deephaven.engine.context.ExecutionContext.getContext()"
    ".getUpdateGraph().clock().currentStep()",
])

ex1_script_ms = (time.perf_counter() - _t0) * 1000
_ug = jpy.get_type("io.deephaven.engine.context.ExecutionContext").getContext().getUpdateGraph()
print(f"[ex1] script body finished in {ex1_script_ms:.1f} ms; update graph = {_ug.getName()}, "
      f"step = {_ug.clock().currentStep()}. ex1_ticks keeps ticking without us.")
