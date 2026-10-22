"""
dhfw: write against the Deephaven Enterprise (Core+) API once; run it on Enterprise
for real, or on a Community server for local development and tests.

    from dhfw import db, remote_table, log_table, meta_import, today, runtime

    quotes = db.live_table("MarketUs", "QuoteStock").where(f"Date == `{today()}`")
    risk   = remote_table("RiskEngine", "desk_risk").subscribe()

On Enterprise every name forwards to the real deephaven_enterprise object. On
Community it is an emulation built from Community constructs; each emulation
states its limits in its docstring and in LIMITATIONS below. Engine operations,
listeners, deephaven.ui and update graphs are the same engine on both and are
NOT wrapped; use the deephaven package directly.
"""
from dhfw.runtime import runtime, is_enterprise, today, effective_user  # noqa: F401
from dhfw.database import db  # noqa: F401
from dhfw.remote import remote_table, resolve_uri  # noqa: F401
from dhfw.systable import log_table, log_table_incremental  # noqa: F401
from dhfw.controller import meta_import, exec_script  # noqa: F401
from dhfw.acl import apply_acl  # noqa: F401

LIMITATIONS = {
    "db.live_table": "Community: a registered feed, a table appended through db.append_live_table/log_table, "
                     "or (replay mode) a historical partition replayed at 1x wall-clock speed.",
    "db.historical_table": "Community: parquet under DHFW_DATA_ROOT/<ns>/<table>/ (key=value partitions). "
                           "No Enterprise schema service, no ACLs, no merge jobs.",
    "db input tables": "Community: in-memory keyed input tables; contents are lost on restart.",
    "replay": "Community: TableReplayer at 1x; now()/today() inside query strings stay wall-clock; "
              "use dhfw.today() in Python for the replay date.",
    "remote_table": "Community: a Barrage subscription (deephaven.barrage) to the server DHFW_PQ_MAP names, "
                    "with anonymous, basic or PSK auth and optional TLS; filters/included_columns are applied on "
                    "the remote server via a pydeephaven shared ticket; no automatic reconnect policy.",
    "log_table": "Community: appends to the in-process live table; no Intraday storage, no tailer, "
                 "nothing survives a restart.",
    "controller_import": "Community: modules come from a local checkout at DHFW_CONTROLLER_ROOT, "
                         "not from the PQ controller's Git repository.",
    "acl_generator / edge_acl": "Community: no-op (anonymous or PSK auth; no row/column ACLs).",
    "not emulated": "PQ scheduling, restarts, failover, query servers, merge/validation jobs, "
                    "Enterprise auth and ACL enforcement, performance_overview.",
}

