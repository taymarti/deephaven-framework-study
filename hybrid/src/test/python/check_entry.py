"""
Check a running hybrid server from a client: which fields exist and where (scope or app),
that the Java tables tick, and that the Python alert action keeps up with the Java listener.

    .venv/Scripts/python hybrid/src/test/python/check_entry.py 10012
"""
import sys
import time

from pydeephaven import Session
from pydeephaven.ticket import ApplicationTicket, ScopeTicket

port = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
s = Session(host="localhost", port=port)
where = {f.field_name: f.application_id for f in s._fetch_fields() if f.field_name.startswith("hy_")}
print("fields (name -> app):", where)


def get(name):
    app = where[name]
    t = ScopeTicket.scope_ticket(name) if app == "scope" else ApplicationTicket.app_ticket(app, name)
    return s.fetch_table(t).to_arrow().to_pandas()


for i in range(3):
    line = f"t+{i * 15}s trades={len(get('hy_trades'))} flips={len(get('hy_flips'))}"
    if "hy_alerts" in where:
        line += f" python_alerts={len(get('hy_alerts'))}"
    print(line, flush=True)
    time.sleep(15)
s.close()
