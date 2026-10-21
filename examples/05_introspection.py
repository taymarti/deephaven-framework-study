"""
Introspection - see the engine's graph and what each node costs.

Run after rungs 2-4. Every table operation and listener is a "performance
entry" in the update graph; the perfmon tables record per-entry timing and
row counts each interval, plus each entry's ANCESTORS. From those, Deephaven
can draw the dataflow graph upstream of any node.

  python examples/run.py examples/05_introspection.py --show ex5_entries --show ex5_hot --tail 25
  Then open in the IDE / iframe:  ex5_graph_ex4, ex5_graph_ex3 (deephaven.ui SVG)
"""
from deephaven import perfmon

# server/app.d/introspection.py opens these at boot, so ancestry is complete.
ex5_upl = perfmon.update_performance_log()               # per-entry, per-interval stats
ex5_ancestors = perfmon.update_performance_ancestors_log()  # entry -> ancestor entries
ex5_server = perfmon.server_state_log()                    # cycle times, memory, GC

# Latest interval per entry: what each node is and what it costs.
ex5_entries = (
    ex5_upl.last_by("EntryId")
    .view(["EntryId", "EntryDescription", "EntryCallerLine", "IntervalEndTime",
           "UsageNanos", "CpuNanos", "InvocationCount",
           "RowsAdded", "RowsModified", "RowsRemoved", "AllocatedBytes"])
)
# Most expensive nodes overall (summed over all intervals so far).
from deephaven import agg

ex5_hot = (
    ex5_upl.agg_by([agg.sum_(["UsageNanos", "Invocations = InvocationCount"]),
                    agg.last("Description = EntryDescription")], by="EntryId")
    .update("UsageMs = UsageNanos / 1e6")
    .sort_descending("UsageNanos")
    .head(15)
    .view(["EntryId", "Description", "UsageMs", "Invocations"])
)


def _entry_id(desc_substring: str) -> int:
    rows = ex5_upl.where(f"EntryDescription.contains(`{desc_substring}`)").select_distinct("EntryId")
    ids = rows.j_table.getColumnSource("EntryId").getLong(rows.j_table.getRowSet().firstRowKey())
    return int(ids)


# Graphs upstream of our two callbacks (needs a couple of perf intervals to
# have been logged after rungs 3-4 started).
ex5_id_ex4 = _entry_id("ex4 synchronizer")
ex5_id_ex3 = _entry_id("ex3 SignalTracker")
ex5_dot_ex4 = perfmon.ancestor_dot(ex5_id_ex4, ex5_upl, ex5_ancestors)  # pure text, always works

# Rendering to SVG needs the graphviz `dot` binary in the server image
# (the stock image lacks it; see server/Dockerfile).
try:
    ex5_graph_ex4 = perfmon.ancestor_image(ex5_id_ex4, ex5_upl, ex5_ancestors)
    ex5_graph_ex3 = perfmon.ancestor_image(ex5_id_ex3, ex5_upl, ex5_ancestors)
except Exception as e:
    print(f"[ex5] SVG rendering unavailable ({type(e).__name__}); use ex5_dot_ex4 instead")
