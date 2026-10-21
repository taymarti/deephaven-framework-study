"""
System table logging (deephaven_enterprise.system_table_logger).

Enterprise: rows go to Intraday storage and other PQs read them with db.live_table.
Community: rows are appended to this worker's emulated live table, so code that
logs and then reads db.live_table behaves the same inside one process. Nothing is
persisted and other processes cannot see it.
"""
import contextlib

from dhfw.runtime import is_enterprise


def log_table(namespace: str, table_name: str, table, columnPartition: str, **kwargs) -> None:
    if is_enterprise():
        from deephaven_enterprise import system_table_logger as stl
        return stl.log_table(namespace, table_name, table, columnPartition, **kwargs)
    from dhfw.database import db
    db.append_live_table(namespace, table_name, columnPartition, table)


def log_table_incremental(namespace: str, table_name: str, table, columnPartition: str, **kwargs):
    """Context manager; hold it open while logging. Community: a listener appends each update's added rows."""
    if is_enterprise():
        from deephaven_enterprise import system_table_logger as stl
        return stl.log_table_incremental(namespace, table_name, table, columnPartition, **kwargs)
    return _local_incremental(namespace, table_name, table, columnPartition)


@contextlib.contextmanager
def _local_incremental(namespace, table_name, table, partition):
    from deephaven.table_listener import listen
    from dhfw.database import db
    db.append_live_table(namespace, table_name, partition, table.snapshot())  # rows present now
    added_only = {"ok": True}

    def on_update(update, is_replay):
        if update.removed() or update.modified():
            added_only["ok"] = False  # Enterprise logging is append-only too; flag it
        rows = update.added()
        if rows:
            from deephaven import new_table
            from deephaven.column import InputColumn
            cols = [InputColumn(c.name, c.data_type, input_data=list(rows[c.name])) for c in table.columns]
            db.append_live_table(namespace, table_name, partition, new_table(cols))

    handle = listen(table, on_update, description=f"dhfw log {namespace}.{table_name}")
    try:
        yield handle
    finally:
        handle.stop()
