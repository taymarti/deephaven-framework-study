"""Probe: ancestry rows around ex2_trades' entry."""
import jpy
from deephaven import perfmon

_bt = jpy.cast(ex2_trades.j_table, jpy.get_type("io.deephaven.engine.table.impl.BaseTable"))
_eid = int(list(_bt.parentPerformanceEntryIds().toArray())[0])
probe_anc = (perfmon.update_performance_ancestors_log()
             .where(f"EntryId >= {_eid - 3} && EntryId <= {_eid + 1}")
             .view(["EntryId", "EntryDescription", "Ancestors"]))
