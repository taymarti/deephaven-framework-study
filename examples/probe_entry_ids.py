"""Probe: can we map a Python Table variable to its update-performance entry id?"""
import jpy
from deephaven import new_table
from deephaven.column import string_col

_names, _vals = [], []
for _n in ["ex2_trades", "ex2_vwap", "ex2_signals", "ex4_orders", "ex4_quotes"]:
    _t = globals().get(_n)
    try:
        _bt = jpy.cast(_t.j_table, jpy.get_type("io.deephaven.engine.table.impl.BaseTable"))
        _ids = list(_bt.parentPerformanceEntryIds().toArray())
    except Exception as e:  # noqa: BLE001
        _ids = f"error: {e}"
    _names.append(_n)
    _vals.append(str(_ids))
probe_ids = new_table([string_col("Var", _names), string_col("ParentPerfEntryIds", _vals)])
