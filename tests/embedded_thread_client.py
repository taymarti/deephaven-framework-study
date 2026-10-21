"""Companion to embedded_thread_demo.py: what does a client's run_script see and change?"""
import json
import os
import pathlib
import time

from pydeephaven import Session

OUT = pathlib.Path(__file__).with_name("embedded_thread_result.json")
PORT = int(os.environ.get("DH_PORT", "10002"))
deadline = time.time() + 240
while not OUT.with_suffix(".ready").exists() and time.time() < deadline:
    time.sleep(1)

s = Session(host="localhost", port=PORT, auth_type="Anonymous")
s.run_script(
    "from deephaven import new_table\nfrom deephaven.column import string_col\n"
    "_seen = [('HOST_STATE visible', str('HOST_STATE' in globals())),\n"
    "         ('HOST_STATE note', str(globals().get('HOST_STATE', {}).get('note'))),\n"
    "         ('embedded_summary visible', str('embedded_summary' in globals()))]\n"
    "if 'HOST_STATE' in globals(): HOST_STATE['modified_by_client'] = True\n"
    "client_view = new_table([string_col('K', [k for k, _ in _seen]), string_col('V', [v for _, v in _seen])])\n"
)
view = {r.K: r.V for r in s.open_table("client_view").to_arrow().to_pandas().itertuples()}
fields = sorted(f.field_name for f in s._fetch_fields())  # noqa: SLF001
view["fields_include_embedded_summary"] = str("embedded_summary" in fields)
s.close()
OUT.with_suffix(".client").write_text(json.dumps(view), encoding="utf-8")
print(json.dumps(view, indent=2))
