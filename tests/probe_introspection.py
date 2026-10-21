"""
End-to-end check of introspect/: load rungs 2-4, hold a client-side export
(a sorted view that exists in no scope), wait for a perf-log interval, then run
the introspection client and check the report finds what we know is there.

  python tests/probe_introspection.py
"""
import json
import pathlib
import subprocess
import sys
import time

from pydeephaven import Session

ROOT = pathlib.Path(__file__).resolve().parents[1]
s = Session(host="localhost", port=10000, auth_type="Anonymous")
for ex in ("02_declarative_dag.py", "03_listener_hook.py", "04_feeds_and_checkpoints.py"):
    s.run_script((ROOT / "examples" / ex).read_text(encoding="utf-8"))
held = s.open_table("ex2_trades").sort_descending("Px").head(20)  # a client export: named nowhere
print("loaded rungs 2-4; holding a client export; waiting 75 s for a perf interval...", flush=True)
time.sleep(75)

out = ROOT / "tests" / "introspection_report.json"
proc = subprocess.run([sys.executable, str(ROOT / "introspect" / "dh_introspect_client.py"), "--json", str(out)],
                      capture_output=True, text=True, encoding="utf-8")
print(proc.stdout[-6000:])
if proc.returncode:
    print(proc.stderr[-3000:])
    sys.exit(proc.returncode)

rep = json.loads(out.read_text(encoding="utf-8"))
nodes = [n for n in rep["graph"]["nodes"] if n.get("active")]
checks = {
    "no section errors": not rep["errors"],
    "server fields include probe.second app": any(f["application_id"] == "probe.second" for f in rep["server_fields"]),
    "scope exports include ex2_signals": any(e["name"] == "ex2_signals" for e in rep["exports"]),
    "input/publisher-fed tables seen": any("blink" in (n["label"] or "") for n in nodes),
    "ex3 + ex4 listeners in graph": {"ex3 SignalTracker", "ex4 synchronizer"} <= {l["description"] for l in rep["listeners"]["in_graph"]},
    "listener handles in scope": len(rep["listeners"]["handles_in_scope"]),
    "unreachable (client/orphan) active nodes": sum(1 for n in nodes if not n["reachable_from_scope"] and n["kind"] != "internal"),
    "asyncio thread seen": any("ex4" in t["name"] for t in rep["runtime"]["python_threads"]),
    "ancestry complete": rep["graph"]["ancestry_complete"],
    "dhi_* cleaned up": not any(f["field_name"].startswith("dhi_") for f in rep["server_fields"]),
}
print(json.dumps(checks, indent=2))
held.close()
s.close()
