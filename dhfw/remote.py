"""
Tables owned by other PQs.

Enterprise: deephaven_enterprise.remote_table (Barrage subscription inside the
cluster, or another cluster with credentials) and pq:// URIs.

Community: each PQ name maps to a Deephaven server in DHFW_PQ_MAP (JSON):

    {"RiskEngine": "localhost:10001",                       # anonymous
     "Pricing":    {"host": "pricing", "port": 10000,
                    "auth_type": "psk",                      # anonymous | basic | psk | <handler class>
                    "auth_token_env": "PRICING_PSK",         # the secret is read from this env var
                    "use_tls": false},
     "Local":      "self"}                                   # a global in this worker

The subscription is a Barrage subscription made by this server
(deephaven.barrage), so the result is a ticking table in the local graph.
With filters / included_columns, pydeephaven first shapes the table ON THE
REMOTE SERVER and publishes it under a shared ticket; only the shaped rows and
columns cross the wire. The publishing pydeephaven session is kept open (an
existing subscription survives its close, but a re-subscribe would not); close
them with close_all().
"""
import json
import os
import threading
from typing import List, Optional

from dhfw.runtime import is_enterprise

_AUTH = {"anonymous": "Anonymous", "basic": "Basic",
         "psk": "io.deephaven.authentication.psk.PskAuthenticationHandler"}
_lock = threading.Lock()
_shapers = []  # pydeephaven sessions that publish shaped tables; must outlive re-subscriptions


def _pq_map() -> dict:
    return json.loads(os.environ.get("DHFW_PQ_MAP", "{}"))


def _target(query: str) -> dict:
    t = _pq_map().get(query)
    if t is None:
        raise KeyError(f"PQ '{query}' not in DHFW_PQ_MAP")
    if t == "self":
        return {"self": True}
    if isinstance(t, str):
        host, _, port = t.rpartition(":")
        t = {"host": host, "port": int(port)}
    auth = t.get("auth_type", "anonymous")
    token = os.environ.get(t["auth_token_env"], "") if t.get("auth_token_env") else ""
    return {"host": t["host"], "port": int(t.get("port", 10000)), "auth_type": _AUTH.get(auth.lower(), auth),
            "auth_token": token, "use_tls": bool(t.get("use_tls", False))}


def _barrage(t: dict):
    from deephaven.barrage import barrage_session  # cached per target by Deephaven
    return barrage_session(host=t["host"], port=t["port"], auth_type=t["auth_type"],
                           auth_token=t["auth_token"], use_tls=t["use_tls"])


def _shaped_ticket(t: dict, table: str, filters, columns) -> bytes:
    """Shape on the remote server with pydeephaven; return the shared ticket's bytes."""
    from pydeephaven import Session
    from pydeephaven.ticket import SharedTicket
    s = Session(host=t["host"], port=t["port"], auth_type=t["auth_type"], auth_token=t["auth_token"],
                use_tls=t["use_tls"])
    remote = s.open_table(table)
    if filters:
        remote = remote.where(filters)
    if columns:
        remote = remote.view(columns)
    ticket = SharedTicket.random_ticket()
    s.publish_table(ticket, remote)
    with _lock:  # keep the session AND the table: dropping the pydeephaven Table releases its export
        _shapers.append((s, remote))
    return ticket.bytes


class _LocalRemoteTableBuilder:
    """Community stand-in for RemoteTableBuilder (same method names)."""

    def __init__(self, query_name: str, table_name: str):
        self._query, self._table = query_name, table_name

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

    def _local_global(self):
        import __main__
        return getattr(__main__, self._table)

    def subscribe(self, clear_on_disconnect: bool = None, retry_window_millis: int = None,
                  max_retries_within_window: int = None, included_columns: Optional[List[str]] = None,
                  filters: Optional[List[str]] = None):
        """A ticking local table. filters / included_columns are applied on the remote server.
        Not emulated: clear_on_disconnect and the retry_* reconnect policy."""
        t = _target(self._query)
        if t.get("self"):
            src = self._local_global()
            src = src.where(filters) if filters else src
            return src.view(included_columns) if included_columns else src
        if filters or included_columns:
            ticket = _shaped_ticket(t, self._table, filters, included_columns)
        else:
            ticket = f"s/{self._table}".encode()
        return _barrage(t).subscribe(ticket)

    def snapshot(self, included_columns: Optional[List[str]] = None):
        t = _target(self._query)
        if t.get("self"):
            src = self._local_global()
            return (src.view(included_columns) if included_columns else src).snapshot()
        ticket = _shaped_ticket(t, self._table, None, included_columns) if included_columns \
            else f"s/{self._table}".encode()
        return _barrage(t).snapshot(ticket)


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


def close_all() -> None:
    """Close the pydeephaven sessions that publish shaped tables (existing subscriptions keep ticking)."""
    with _lock:
        while _shapers:
            _shapers.pop()[0].close()
