"""Probe: what introspection does this Deephaven build expose?"""
import inspect
import jpy
from deephaven import new_table, perfmon
from deephaven.column import string_col

_rows = []
for name, fn in inspect.getmembers(perfmon, inspect.isfunction):
    if fn.__module__ == perfmon.__name__ and not name.startswith("_"):
        doc = (fn.__doc__ or "").strip()
        _rows.append((name, str(inspect.signature(fn)), doc.replace("\n", " ")[:600]))

probe_perfmon = new_table([
    string_col("Function", [r[0] for r in _rows]),
    string_col("Signature", [r[1] for r in _rows]),
    string_col("Doc", [r[2] for r in _rows]),
])
