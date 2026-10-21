"""
Tables owned by other PQs.

Enterprise: deephaven_enterprise.remote_table (Barrage subscription inside the
cluster, or another cluster with credentials) and pq:// URIs.
Community: each PQ name maps to a local Community server (DHFW_PQ_MAP, JSON like
{"RiskEngine": "localhost:10001"}); the subscription is a dh+plain Barrage URI.
A PQ name mapped to "self" resolves to a global in this worker.
"""
import json
import os
from typing import List, Optional

from dhfw.runtime import is_enterprise


def _pq_map() -> dict:
    return json.loads(os.environ.get("DHFW_PQ_MAP", "{}"))


class _LocalRemoteTableBuilder:
    """Community stand-in for RemoteTableBuilder (same method names)."""

    def __init__(self, query_name: str, table_name: str):
        self._query, self._table, self._blink = query_name, table_name, False

    def query_name(self, q):
        self._query = q
        return self

    def table_name(self, t):
        self._table = t
        return self

    def table_definition(self, _definition):
        return self  # Community resolves the live definition; an unreachable source fails instead of waiting

    def blink(self, is_blink: bool):
        if is_blink:
            raise NotImplementedError("blink remote tables are not emulated on Community")
        return self

    def _resolve(self):
        target = _pq_map().get(self._query)
        if target is None:
            raise KeyError(f"PQ '{self._query}' not in DHFW_PQ_MAP")
        if target == "self":
            import __main__
            return getattr(__main__, self._table)
        from deephaven.uri import resolve
        return resolve(f"dh+plain://{target}/scope/{self._table}")

    def subscribe(self, clear_on_disconnect: bool = None, retry_window_millis: int = None,
                  max_retries_within_window: int = None, included_columns: Optional[List[str]] = None,
                  filters: Optional[List[str]] = None):
        """Live subscription. Limits: filters and columns are applied after the whole table arrives;
        no reconnect policy (clear_on_disconnect / retry_* are ignored)."""
        t = self._resolve()
        if filters:
            t = t.where(filters)
        if included_columns:
            t = t.view(included_columns)
        return t

    def snapshot(self, included_columns: Optional[List[str]] = None):
        t = self._resolve()
        t = t.view(included_columns) if included_columns else t
        return t.snapshot()


def remote_table(query_name: str, table_name: str, table_definition=None):
    """Same call on both runtimes: remote_table("RiskEngine", "desk_risk").subscribe(filters=[...])."""
    if is_enterprise():
        from deephaven_enterprise import remote_table as rt
        return rt.in_local_cluster(query_name, table_name, table_definition)
    return _LocalRemoteTableBuilder(query_name, table_name)


def resolve_uri(uri: str):
    """pq://<PQ>/scope/<table> on Enterprise; mapped to remote_table(...).subscribe() on Community."""
    if is_enterprise() or not uri.startswith("pq://"):
        from deephaven.uri import resolve
        return resolve(uri)
    query, kind, table = uri[len("pq://"):].split("/", 2)
    if kind != "scope":
        raise ValueError(f"only pq://<PQ>/scope/<table> is emulated, got {uri}")
    return remote_table(query, table).subscribe()
