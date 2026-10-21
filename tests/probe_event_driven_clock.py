"""
Probe (run via run_script): can OUR code own the clock?

Builds an event-driven update graph, a table_publisher feed on it, a derived
aggregate and a Python listener, then pushes rows WITHOUT refreshing, and only
afterwards calls requestRefresh(). If the graph is ours, nothing propagates
until we say so, and one refresh delivers everything pushed since the last one.
"""
import time

import jpy
from deephaven import agg, new_table
from deephaven import dtypes as dht
from deephaven.column import double_col, long_col, string_col
from deephaven.execution_context import ExecutionContext, get_exec_ctx
from deephaven.stream.table_publisher import table_publisher
from deephaven.table_listener import listen
from deephaven.update_graph import UpdateGraph

_EDUG = jpy.get_type("io.deephaven.engine.updategraph.impl.EventDrivenUpdateGraph")
try:
    _ug = _EDUG.newBuilder("synchronizer_clock").build()
except Exception:  # noqa: BLE001 - re-run: the name is already registered
    _ug = jpy.get_type("io.deephaven.engine.updategraph.impl.BaseUpdateGraph").getInstance("synchronizer_clock")
_ctx = ExecutionContext(j_exec_ctx=get_exec_ctx().j_exec_ctx.withUpdateGraph(_ug))
_events = []

with _ctx:
    _blink, _pub = table_publisher("sync_feed", {"Sym": dht.string, "Qty": dht.int64},
                                   update_graph=UpdateGraph(j_update_graph=_ug))
    _sums = _blink.agg_by([agg.sum_("Qty"), agg.count_("Rows")], by="Sym")  # blink agg: per-step totals
    _h = listen(_sums, lambda u, r: _events.append(("callback", _ug.clock().currentStep(),
                                                    dict(zip(u.added().get("Sym", []), u.added().get("Qty", []))) or
                                                    dict(zip(u.modified().get("Sym", []), u.modified().get("Qty", []))))))

    _log = [("start step", _ug.clock().currentStep())]
    for q in (100, 200, 300):  # three pushes, no refresh yet
        _pub.add(new_table([string_col("Sym", ["A"]), long_col("Qty", [q])]))
    time.sleep(1.5)  # more than a periodic cycle: nothing should happen on its own
    _log.append(("after pushes + 1.5 s idle: step / callbacks", f"{_ug.clock().currentStep()} / {len(_events)}"))
    _ug.requestRefresh()  # OUR checkpoint
    time.sleep(0.5)
    _log.append(("after requestRefresh: step / callbacks", f"{_ug.clock().currentStep()} / {len(_events)}"))
    _pub.add(new_table([string_col("Sym", ["A", "B"]), long_col("Qty", [5, 7])]))
    _ug.requestRefresh()
    time.sleep(0.5)
    _log.append(("after second push + refresh: step / callbacks", f"{_ug.clock().currentStep()} / {len(_events)}"))
    _h.stop()

probe_clock = new_table([
    string_col("Check", [k for k, _ in _log] + [f"event {i}" for i in range(len(_events))]),
    string_col("Value", [str(v) for _, v in _log] + [str(e) for e in _events]),
])
