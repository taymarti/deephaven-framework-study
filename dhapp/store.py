"""
Persistence recipes: the four kinds of table an app owns, each on the right store.

| You want                                      | Use                  | Enterprise                         | Community (dhfw)            |
|-----------------------------------------------|----------------------|------------------------------------|-----------------------------|
| an end-of-day or on-demand snapshot           | snapshot()           | user table (db.add_unpartitioned_table) | parquet file           |
| one partition per day, queryable as history   | daily_partition()    | partitioned user table             | parquet Date=... folders    |
| a live log other PQs can read with live_table | intraday_log()       | system_table_logger (Intraday)     | in-process live table only  |
| editable state (limits, overrides)            | state_table()        | db input table (persistent)        | in-memory input table       |

Reading any of them back is always db.historical_table / db.live_table / db.input_table.
"""
import contextlib

from dhfw import db, log_table_incremental, today


def snapshot(table, namespace: str, name: str) -> None:
    """Overwrite a whole user table with the table's current contents."""
    db.delete_unpartitioned_table(namespace, name)
    db.add_unpartitioned_table(namespace, name, table.snapshot())


def daily_partition(table, namespace: str, name: str, date: str = None, column: str = "Date") -> None:
    """Write today's (or `date`'s) partition; creates the schema on first use."""
    if name not in db.table_names(namespace):
        db.add_partitioned_table_schema(namespace, name, column, table.head(0))
    db.add_table_partition(namespace, name, date or today(), table.snapshot())


@contextlib.contextmanager
def intraday_log(table, namespace: str, name: str, date: str = None):
    """Log every added row while the block is open (append-only tables)."""
    with log_table_incremental(namespace, name, table, date or today()) as handle:
        yield handle


def state_table(namespace: str, name: str, prototype, keys):
    """A keyed, editable table (create once, then reuse). Edits come from UIs or code via .add()."""
    if name not in db.table_names(namespace):
        db.add_input_table_schema_from_table(namespace, name, prototype, keys)
    return db.input_table(namespace, name)
