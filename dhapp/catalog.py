"""
Location-transparent tables: code asks for a LOGICAL name; the catalog decides how
to reach it from wherever the app is running.

    catalog = Catalog({
        "quotes":      {"db": ["MarketUs", "QuoteStock"]},                       # plant database
        "desk_limits": {"pq": "RiskLimits", "table": "desk_limits", "plant": "ny"},
        "fx_rates":    {"pq": "FxRates", "table": "rates", "plant": "ldn"},
    }, plants={"ldn": {"url": "https://ldn-dh.example/iris/connection.json", "key_file": "/etc/dh/ldn.key"}})

Where am I?  DHFW_PLANT (this plant's name) and DHFW_PQ (this PQ's name), set in the
PQ's settings on Enterprise and in your shell locally.

| Entry           | Same PQ                | Same plant                 | Another plant                            | Community (laptop)                     |
|-----------------|------------------------|----------------------------|------------------------------------------|----------------------------------------|
| {"pq": ...}     | the global in this PQ  | remote_table.in_local_cluster | remote_table.for_remote_cluster(url)  | DHFW_PQ_MAP: a local server or "self"  |
| {"db": [ns,t]}  | db.live_table / historical_table on the plant                                          | dhfw's local emulation          |
| override(name)  | a fixture or local feed, any runtime (tests)                                                                  |

Rules this enforces: app code never names a host, a PQ or a plant; moving a PQ, or
deploying onto the plant that owns a table, changes the catalog's answer, not the code.
"""
import os
from typing import Callable, Optional, Union

from dhfw import db, is_enterprise
from dhfw.remote import remote_table


class Catalog:
    def __init__(self, entries: Optional[dict] = None, plants: Optional[dict] = None):
        self.entries = dict(entries or {})
        self.plants = dict(plants or {})
        self._overrides = {}

    @property
    def here(self) -> dict:
        return {"plant": os.environ.get("DHFW_PLANT"), "pq": os.environ.get("DHFW_PQ")}

    def override(self, name: str, table_or_factory: Union[object, Callable]) -> None:
        """Pin a logical name to a fixture table or local feed (tests, demos)."""
        self._overrides[name] = table_or_factory

    def binding(self, name: str) -> str:
        """How `name` would be reached from here, in words (shown on the dashboard)."""
        if name in self._overrides:
            return "override"
        e = self.entries[name]
        if "db" in e:
            return f"db {'live' if e.get('live', True) else 'historical'} {e['db'][0]}.{e['db'][1]}"
        where = self._where(e)
        return {"self": f"local global '{e['table']}'", "plant": f"same plant PQ {e['pq']}",
                "remote": f"plant {e.get('plant')} PQ {e['pq']}"}[where]

    def resolve(self, name: str, subscribe_kwargs: Optional[dict] = None):
        if name in self._overrides:
            o = self._overrides[name]
            return o() if callable(o) else o
        e = self.entries[name]
        if "db" in e:
            ns, t = e["db"]
            return db.live_table(ns, t) if e.get("live", True) else db.historical_table(ns, t)
        kw = subscribe_kwargs or {}
        where = self._where(e)
        if where == "self":
            import __main__
            return getattr(__main__, e["table"])
        if where == "remote" and is_enterprise():
            plant = self.plants[e["plant"]]
            from deephaven_enterprise import remote_table as rt
            builder = rt.for_remote_cluster(plant["url"])
            builder = builder.private_key(plant["key_file"]) if "key_file" in plant else \
                builder.password(plant["user"], os.environ[plant["password_env"]])
            return builder.query_name(e["pq"]).table_name(e["table"]).subscribe(**kw)
        # same plant on Enterprise, or any remote on Community (dhfw maps PQ names to local servers)
        return remote_table(e["pq"], e["table"]).subscribe(**kw)

    def _where(self, e: dict) -> str:
        here = self.here
        if here["pq"] and e["pq"] == here["pq"] and (not e.get("plant") or e.get("plant") == here["plant"]):
            return "self"
        if not e.get("plant") or e.get("plant") == here["plant"]:
            return "plant"
        return "remote"
