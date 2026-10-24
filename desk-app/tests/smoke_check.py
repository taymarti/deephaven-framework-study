"""
End-to-end check of an installed dh-desk (run by smoke.py, from the fresh venv):

  server  every table is published; Java pricing produced numbers; spot ticks
  flow    lowering a desk limit -> Java tracker emits BREACH -> Python action writes an alert;
          restoring it -> CLEAR
  web     dh-desk-web serves the React build and proxies Deephaven's JS API

    python tests/smoke_check.py --server-port 10020 --web-port 4020
"""
import argparse
import sys
import time
import urllib.request

from pydeephaven import Session


def wait_until(fn, timeout=20.0, every=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value is not None:  # a DataFrame/Series has no truth value
            return value
        time.sleep(every)
    return None


def matching(frame, **eq):
    """frame if any row has all the given column values, else None (for wait_until)."""
    mask = True
    for col, val in eq.items():
        mask = mask & (frame[col] == val)
    return frame if mask.any() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-port", type=int, default=10000)
    ap.add_argument("--web-port", type=int, default=4010)
    a = ap.parse_args()
    s = Session(host="localhost", port=a.server_port)

    def df(name):
        return s.open_table(name).to_arrow().to_pandas()

    failures = []

    def check(name, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)
        if not ok:
            failures.append(name)

    fields = {f.field_name for f in s._fetch_fields()}
    want = {"spot", "positions", "book", "risk", "limits", "tickets", "breach_events", "alerts", "desk_ops"}
    check("all tables and the ops dashboard are published", want <= fields, str(sorted(want - fields)))

    book = df("book")
    check("Java pricing filled Price/Delta for every position", len(book) > 0 and book[["Price", "Delta"]].notna().all().all(),
          f"{len(book)} positions")
    s1 = df("spot").set_index("Underlying")["Spot"]

    def spot_moved():
        s2 = df("spot").set_index("Underlying")["Spot"]
        return None if s2.equals(s1) else s2

    s2 = wait_until(spot_moved, 10)
    check("spot prices tick", s2 is not None)

    risk = df("risk").set_index("Desk")
    tech = abs(risk.loc["Tech", "DeltaDollars"])
    s.run_script("from deephaven import new_table\nfrom deephaven.column import string_col, double_col\n"
                 f"limits.add(new_table([string_col('Desk', ['Tech']), double_col('DeltaLimit', [{tech / 2:.2f}])]))")
    ev = wait_until(lambda: matching(df("breach_events"), Desk="Tech", Event="BREACH"))
    check("lowering Tech's limit -> Java tracker emits BREACH", ev is not None)
    al = wait_until(lambda: matching(df("alerts"), Desk="Tech"))
    check("-> Python action writes an alert", al is not None, "" if al is None else al["Message"].iloc[-1])
    s.run_script("limits.add(new_table([string_col('Desk', ['Tech']), double_col('DeltaLimit', [1e9])]))")
    cl = wait_until(lambda: matching(df("breach_events"), Desk="Tech", Event="CLEAR"))
    check("restoring it -> CLEAR", cl is not None)
    s.close()

    base = f"http://localhost:{a.web_port}"
    html = urllib.request.urlopen(base + "/").read().decode()
    check("dh-desk-web serves the React build", '<div id="root">' in html)
    asset = html.split('src="')[1].split('"')[0] if 'src="' in html else ""
    check("its JS bundle is served", bool(asset) and urllib.request.urlopen(base + asset).status == 200, asset)
    js = urllib.request.urlopen(base + "/jsapi/dh-core.js")
    check("the Deephaven JS API is proxied through it", js.status == 200 and len(js.read()) > 100_000)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
