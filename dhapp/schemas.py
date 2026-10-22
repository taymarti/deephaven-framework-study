"""
Standard table shapes. Recipes compose because they agree on these column names.
A schema is a plain {column: dtype} dict (what table_publisher and input_table take).
"""
from deephaven import dtypes as dht

QUOTES = {"Timestamp": dht.Instant, "Sym": dht.string, "Bid": dht.double, "Ask": dht.double}
TRADES = {"Timestamp": dht.Instant, "Sym": dht.string, "Px": dht.double, "Qty": dht.int64}
DESKS = {"Sym": dht.string, "Desk": dht.string}
LIMITS = {"Desk": dht.string, "Limit": dht.double}


class SchemaError(ValueError):
    pass


def validate(table, schema: dict, name: str = "table"):
    """Fail at the boundary, not three stages later: every schema column present with its type."""
    have = {c.name: c.data_type for c in table.columns}
    missing = [c for c in schema if c not in have]
    wrong = [f"{c}: {have[c]} != {t}" for c, t in schema.items() if c in have and have[c] != t]
    if missing or wrong:
        raise SchemaError(f"{name}: missing {missing} wrong types {wrong}")
    return table
