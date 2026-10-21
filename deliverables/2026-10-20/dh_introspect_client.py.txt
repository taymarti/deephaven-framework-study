"""
Introspect the application a Deephaven worker is running, from any machine
with network access to it.

  python introspect/dh_introspect_client.py                       # localhost:10000, anonymous
  python introspect/dh_introspect_client.py --psk 's3cret' --json report.json
  python introspect/dh_introspect_client.py --keep                # leave dhi_* tables in the worker to browse

What it does:
  1. Lists the server's exported FIELDS - the registry every client (IDE, JS,
     Python) reads. It includes fields applications publish under their own
     ids (ApplicationState), which need not be names in the console scope, with
     their object types (Table, Figure, deephaven.ui.Element...).
  2. Sends dh_introspect.py with run_script and executes it in its own namespace
     inside the worker, so the console scope only gains `dhi_*` report tables.
  3. Reads the JSON report back, merges in the field list, prints it, and
     (unless --keep) removes what it added, even if the report failed.

Running code in a worker needs console access to it (on Enterprise: a PQ you
are allowed to run scripts against). The report code only reads, apart from
opening the engine's performance logs and binding its `dhi_*` report tables
(any existing `dhi_*` names in the console scope are replaced, then removed).

Why both halves (verified on Community 42.6, see VERIFIED_FACTS.md):
  * The field list is the authoritative "what is exposed": every application's
    fields, underscore names included, with their object types.
  * run_script executes in the worker's single global scope and on the script
    session's thread, which holds a real execution context, so the in-worker
    half can build its report tables there.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from pydeephaven import Session

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dh_introspect import render_text  # noqa: E402  (pure Python; no deephaven needed locally)

_RUN = """
_dhi_ns = {{'__name__': 'dh_introspect'}}
exec(compile({src!r}, 'dh_introspect.py', 'exec'), _dhi_ns)
_dhi_ns['introspect'](scope=globals(), publish=True, include_private={private!r})
"""
_CLEANUP = """
for _dhi_k in [k for k in list(globals()) if k.startswith('dhi_')] + ['_dhi_ns']:
    globals().pop(_dhi_k, None)
globals().pop('_dhi_k', None)
"""


def server_fields(session: Session) -> list:
    # pydeephaven has no public "list fields" call; _fetch_fields() is what
    # Session.tables uses internally (one ListFields snapshot).
    out = []
    for f in session._fetch_fields():  # noqa: SLF001
        out.append({"application_id": f.application_id, "application_name": f.application_name,
                    "field_name": f.field_name, "type": f.typed_ticket.type,
                    "description": f.field_description})
    return sorted(out, key=lambda x: (x["application_id"] != "scope", x["application_id"], x["field_name"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=10000)
    ap.add_argument("--psk", help="pre-shared key (omit for anonymous auth)")
    ap.add_argument("--json", help="also write the full report to this file")
    ap.add_argument("--keep", action="store_true", help="leave dhi_* tables in the worker")
    ap.add_argument("--private", action="store_true",
                    help="also list underscore names that are not exportable (exportable ones are always "
                         "listed: they are published as fields)")
    args = ap.parse_args()

    auth = ({"auth_type": "io.deephaven.authentication.psk.PskAuthenticationHandler", "auth_token": args.psk}
            if args.psk else {"auth_type": "Anonymous"})
    session = Session(host=args.host, port=args.port, **auth)
    try:
        fields = server_fields(session)
        src = (HERE / "dh_introspect.py").read_text(encoding="utf-8")
        session.run_script(_CLEANUP)  # never read a stale dhi_report left by an earlier --keep run
        session.run_script(_RUN.format(src=src, private=args.private))
        rep = json.loads(session.open_table("dhi_report").to_arrow().to_pandas().Json[0])
        # hide only our own report tables (scope app); other apps' dhi_* fields stay listed
        rep["server_fields"] = [f for f in fields
                                if not (f["application_id"] == "scope" and f["field_name"].startswith("dhi_"))]
    finally:
        try:
            if not args.keep:
                session.run_script(_CLEANUP)
        finally:
            session.close()

    if args.json:  # before printing: a console that cannot encode the text must not cost the report
        pathlib.Path(args.json).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")
    print(render_text(rep))
    if args.json:
        print(f"\nfull report: {args.json}")


if __name__ == "__main__":
    main()
