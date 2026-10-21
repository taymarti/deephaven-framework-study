"""
Measure the scope / field / ticket claims against a live Community server.

Start the server with the probe apps:
  python server/run_server.py --app-dir tests/probe_app.d
then:
  python tests/probe_concepts.py
"""
import json

import pandas as pd
from pydeephaven import Session
from pydeephaven.ticket import SharedTicket

pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 90)
R = {}


def new_session():
    return Session(host="localhost", port=10000, auth_type="Anonymous")


def fields(s):
    return [(f.application_id, f.field_name, f.typed_ticket.type) for f in s._fetch_fields()]  # noqa: SLF001


def table(s, name):
    return s.open_table(name).to_arrow().to_pandas()


s = new_session()

# 1. run_script runs in the global scope: a name from one call is visible to the next.
s.run_script("from deephaven import empty_table\nprobe_rs_a = empty_table(2).update('X = i')")
s.run_script("probe_rs_b = probe_rs_a.update('Y = X * 10')")
R["1 run_script shares one global scope"] = list(table(s, "probe_rs_b").Y)

# 2/3/4. Field registry after boot: which app ids exist, where each probe name landed.
f0 = fields(s)
R["3 application ids in this worker"] = sorted({a for a, _, _ in f0})
R["2/4 probe fields (app id, name, type)"] = sorted(x for x in f0 if "probe" in x[1] or x[1] == "second_only")
s.run_script("_rs_underscore = empty_table(1)")
R["4 console-defined _rs_underscore is a field"] = any(n == "_rs_underscore" for _, n, _ in fields(s))
s.run_script(
    "from deephaven import new_table\nfrom deephaven.column import string_col\n"
    "probe_scope_check = new_table([string_col('Name', ['probe_plain', 'probe_global', '_probe_underscore']),"
    " string_col('InConsoleGlobals', [str(n in globals()) for n in ['probe_plain', 'probe_global', '_probe_underscore']])])"
)
R["2 visible from the console's globals()"] = table(s, "probe_scope_check").to_dict("records")
# Application ticket: fetch an app-only field directly by (app id, field).
from pydeephaven.ticket import ApplicationTicket  # noqa: E402
from pydeephaven.table import Table  # noqa: E402

t1 =Table(session=s, ticket=s.fetch(ApplicationTicket.app_ticket("probe.scoping", "probe_env")))
R["2 app script namespace (probe_env)"] = t1.to_arrow().to_pandas().to_dict("records")
for app_id in ("probe.scoping", "probe.second"):
    tt = Table(session=s, ticket=s.fetch(ApplicationTicket.app_ticket(app_id, "probe_field")))
    R[f"5b same field name in {app_id}"] = list(tt.to_arrow().to_pandas().Src)

# Export ticket format.
exp = s.open_table("probe_rs_b")
R["7 export ticket bytes"] = {"prefix": exp.ticket.bytes[:1].decode(), "length": len(exp.ticket.bytes)}

# URI forms resolved inside the worker.
uris = ["local:///scope/probe_global", "local:///app/probe.scoping/field/probe_field",
        "local:///app/probe.second/field/probe_field", "dh+plain://localhost:10000/scope/probe_global",
        "dh+plain://localhost:10000/app/probe.scoping/field/probe_field"]
s.run_script(
    "from deephaven import uri, new_table\nfrom deephaven.column import string_col\n_r = []\n"
    f"for _u in {uris!r}:\n"
    "    try:\n        _o = uri.resolve(_u); _r.append((_u, 'ok', type(_o).__name__ + ' size=' + str(getattr(_o, 'size', '?'))))\n"
    "    except Exception as _e:\n        _r.append((_u, 'FAIL', str(_e).splitlines()[0][:150]))\n"
    "probe_uri = new_table([string_col('Uri', [x[0] for x in _r]), string_col('Result', [x[1] for x in _r]),"
    " string_col('Detail', [x[2] for x in _r])])"
)
R["8 URI resolution"] = table(s, "probe_uri").to_dict("records")

# 5. bind_table promotes a client export to a field that outlives the session.
s1 = new_session()
s1.bind_table("probe_bound", s1.empty_table(3))
R["5 bound name is a field (while binder open)"] = any(n == "probe_bound" for _, n, _ in fields(s))
s1.close()
s2 = new_session()
R["5 bound name is a field after binder closed"] = any(n == "probe_bound" for _, n, _ in fields(s2))
R["5 bound table rows after binder closed"] = len(table(s2, "probe_bound"))

# 6. Shared ticket: published by s3, fetched by s2, then s3 closes.
s3 = new_session()
shared = SharedTicket.random_ticket()
s3.publish_table(shared, s3.empty_table(4))
early = s2.fetch_table(shared)
R["6 shared fetch while publisher open (rows)"] = early.size
s3.close()
try:
    late = s2.fetch_table(shared)
    R["6 shared fetch after publisher closed"] = f"ok, rows={late.size}"
except Exception as e:  # noqa: BLE001
    R["6 shared fetch after publisher closed"] = f"FAIL: {str(e).splitlines()[0][:120]}"
try:
    R["6 copy fetched earlier still usable"] = f"ok, rows={len(early.to_arrow())}"
except Exception as e:  # noqa: BLE001
    R["6 copy fetched earlier still usable"] = f"FAIL: {str(e).splitlines()[0][:120]}"

s2.close()
s.close()
print(json.dumps(R, indent=2, default=str))
