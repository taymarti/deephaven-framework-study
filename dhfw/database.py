"""
`db`: the Enterprise Database on Enterprise; a local emulation on Community.

Community storage layout (DHFW_DATA_ROOT, default ./dhfw_data):
    <root>/<namespace>/<table>/                       historical, key=value partitions (e.g. Date=2026-10-20/)
    <root>/<namespace>/<table>.parquet                unpartitioned user table
    <root>/<namespace>/<table>/_dhfw.json             partition column name for partitioned schemas

Live tables are in-process: a feed you register (db.register_live), rows appended
through db.append_live_table / dhfw.log_table, or, in replay mode
(DHFW_REPLAY_DATE=YYYY-MM-DD), that date's historical partition replayed at 1x
wall-clock speed through TableReplayer, like an Enterprise replay query.
"""
import json
import os
import pathlib
import threading
from typing import Optional, Sequence

from dhfw.runtime import is_enterprise


def _uri(path: pathlib.Path) -> str:
    """Deephaven parquet parses paths as URIs; on Windows C:\\... is rejected, so pass file:/// URIs."""
    return path.as_uri() if os.name == "nt" else str(path)


class UnsupportedOnCommunity(NotImplementedError):
    """An Enterprise call with no faithful Community emulation."""


def _enterprise_db():
    import __main__
    if hasattr(__main__, "db"):  # Core+ workers bind `db` in the global scope
        return __main__.db
    raise RuntimeError("Enterprise runtime detected but no `db` in the worker's global scope")


class LocalDatabase:
    """Community emulation of deephaven_enterprise.database.Database (the methods our code uses)."""

    def __init__(self, root: Optional[str] = None):
        self.root = pathlib.Path(root or os.environ.get("DHFW_DATA_ROOT", "dhfw_data")).resolve()
        self._live = {}       # (ns, table) -> {"blink": Table, "append": Table, "pub": TablePublisher | None}
        self._inputs = {}     # (ns, table) -> InputTable
        self._replayers = []
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- reads
    def historical_table(self, namespace: str, table_name: str, internal_partition_column=None):
        """Parquet under <root>/<ns>/<table>[.parquet]. Static, like Enterprise historical tables."""
        from deephaven import parquet
        single = self.root / namespace / f"{table_name}.parquet"
        if single.exists():
            return parquet.read(_uri(single))
        part_dir = self.root / namespace / table_name
        if part_dir.is_dir():
            return parquet.read(_uri(part_dir), file_layout=parquet.ParquetFileLayout.KV_PARTITIONED)
        raise KeyError(f"no historical table {namespace}.{table_name} under {self.root}")

    def live_table(self, namespace: str, table_name: str, is_refreshing=None, is_blink: bool = False,
                   internal_partition_column=None):
        """A ticking table: registered feed > appended rows > replay of DHFW_REPLAY_DATE > empty live table."""
        key = (namespace, table_name)
        with self._lock:
            if key not in self._live:
                replay_date = os.environ.get("DHFW_REPLAY_DATE")
                if replay_date and self._has_partition(namespace, table_name, replay_date):
                    self._live[key] = self._replay(namespace, table_name, replay_date)
                else:  # an empty live table with the historical schema; appends make it tick
                    self._publisher(namespace, table_name, self.historical_table(namespace, table_name).head(0))
            entry = self._live[key]
        if is_blink:
            if entry["blink"] is None:
                raise UnsupportedOnCommunity(f"{namespace}.{table_name} has no blink form here")
            return entry["blink"]
        return entry["append"]

    def namespaces(self) -> list:
        disk = {p.name for p in self.root.iterdir() if p.is_dir()} if self.root.exists() else set()
        return sorted(disk | {ns for ns, _ in self._live} | {ns for ns, _ in self._inputs})

    def table_names(self, namespace: str) -> list:
        d = self.root / namespace
        disk = {p.stem for p in d.iterdir()} if d.exists() else set()
        mem = {t for ns, t in list(self._live) + list(self._inputs) if ns == namespace}
        return sorted((disk | mem) - {"_dhfw"})

    def catalog_table(self):
        from deephaven import new_table
        from deephaven.column import string_col
        rows = [(ns, t) for ns in self.namespaces() for t in self.table_names(ns)]
        return new_table([string_col("Namespace", [r[0] for r in rows]), string_col("TableName", [r[1] for r in rows])])

    def table_definition(self, namespace: str, table_name: str):
        try:
            t = self.historical_table(namespace, table_name)
        except KeyError:
            t = self.live_table(namespace, table_name)
        return t.meta_table

    # --------------------------------------------------------------- writes
    def add_unpartitioned_table(self, namespace: str, table_name: str, table) -> None:
        """User table: written as one parquet file; read back with historical_table."""
        from deephaven import parquet
        path = self.root / namespace / f"{table_name}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        parquet.write(table, _uri(path))

    def delete_unpartitioned_table(self, namespace: str, table_name: str) -> bool:
        path = self.root / namespace / f"{table_name}.parquet"
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed

    def add_partitioned_table_schema(self, namespace, table_name, partition_column_name, prototype) -> bool:
        d = self.root / namespace / table_name
        d.mkdir(parents=True, exist_ok=True)
        (d / "_dhfw.json").write_text(json.dumps({"partition_column": partition_column_name}))
        return True

    def add_table_partition(self, namespace, table_name, partition_column_value, table) -> None:
        from deephaven import parquet
        col = self._partition_column(namespace, table_name)
        out = self.root / namespace / table_name / f"{col}={partition_column_value}" / "data.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        parquet.write(table, _uri(out))

    def append_live_table(self, namespace, table_name, partition_column_value, table) -> None:
        """Append rows to the in-process live table (they appear at the next cycle)."""
        self._publisher(namespace, table_name, table).add(table)

    # ---------------------------------------------------------- input tables
    def add_input_table_schema_from_table(self, namespace, table_name, prototype, key_col_names) -> bool:
        from deephaven import input_table
        with self._lock:
            self._inputs[(namespace, table_name)] = input_table(init_table=prototype.head(0), key_cols=key_col_names)
        return True

    def input_table(self, namespace, table_name):
        """In memory only: unlike Enterprise, contents do not survive a restart."""
        return self._inputs[(namespace, table_name)]

    def delete_input_table(self, namespace, table_name) -> bool:
        return self._inputs.pop((namespace, table_name), None) is not None

    # ---------------------------------------------------- community-only API
    def register_live(self, namespace: str, table_name: str, table) -> None:
        """Bind a local feed (table_publisher output, time_table, Kafka, ...) as a 'live table'."""
        with self._lock:
            self._live[(namespace, table_name)] = {"blink": None, "append": table, "pub": None}

    # -------------------------------------------------------------- helpers
    def __getattr__(self, name):
        raise UnsupportedOnCommunity(f"db.{name} has no Community emulation in dhfw; see dhfw.LIMITATIONS")

    def _partition_column(self, namespace, table_name) -> str:
        meta = self.root / namespace / table_name / "_dhfw.json"
        return json.loads(meta.read_text())["partition_column"] if meta.exists() else "Date"

    def _has_partition(self, namespace, table_name, value) -> bool:
        col = self._partition_column(namespace, table_name)
        return (self.root / namespace / table_name / f"{col}={value}").is_dir()

    def _publisher(self, namespace, table_name, prototype):
        from deephaven.stream import blink_to_append_only
        from deephaven.stream.table_publisher import table_publisher
        key = (namespace, table_name)
        with self._lock:
            entry = self._live.get(key)
            if entry is None or entry.get("pub") is None:
                if entry is not None and entry.get("append") is not None:
                    raise UnsupportedOnCommunity(f"{namespace}.{table_name} is a registered feed; it cannot be appended to")
                cols = {c.name: c.data_type for c in prototype.columns}
                blink, pub = table_publisher(f"{namespace}.{table_name}", cols)
                self._live[key] = {"blink": blink, "append": blink_to_append_only(blink), "pub": pub}
            return self._live[key]["pub"]

    def _replay(self, namespace, table_name, date):
        from deephaven import parquet
        from deephaven.replay import TableReplayer
        col = self._partition_column(namespace, table_name)
        hist = parquet.read(_uri(self.root / namespace / table_name / f"{col}={date}" / "data.parquet"))
        from deephaven.pandas import to_pandas
        ts = os.environ.get(f"DHFW_REPLAY_TIMESTAMP_{namespace}_{table_name}", "Timestamp")
        bounds = to_pandas(hist.agg_by(_min_max(ts)))
        rp = TableReplayer(bounds["Lo"][0], bounds["Hi"][0])
        replayed = rp.add_table(hist, ts)
        rp.start()
        self._replayers.append(rp)
        return {"blink": None, "append": replayed, "pub": None}


def _min_max(ts):
    from deephaven import agg
    return [agg.min_(f"Lo = {ts}"), agg.max_(f"Hi = {ts}")]


class _DbProxy:
    """`from dhfw import db` works at import time; the real object is resolved on first use."""
    _target = None

    def _get(self):
        if _DbProxy._target is None:
            _DbProxy._target = _enterprise_db() if is_enterprise() else LocalDatabase()
        return _DbProxy._target

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def __repr__(self):
        return f"<dhfw.db -> {type(self._get()).__name__}>"


db = _DbProxy()

