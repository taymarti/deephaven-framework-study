"""
Tiny driver for the examples: sends a script to the running Deephaven server
(exactly like pasting it into the IDE console at http://localhost:10000/ide/),
then optionally snapshots tables so you can watch them change.

  python examples/run.py examples/01_lifecycle.py
  python examples/run.py --show ex1_ticks --every 2 --times 3
  python examples/run.py examples/02_declarative_dag.py --show ex2_signals
"""
import argparse
import time

import pandas as pd
from pydeephaven import Session

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)

ap = argparse.ArgumentParser()
ap.add_argument("scripts", nargs="*", help="example scripts to run, in order")
ap.add_argument("--show", action="append", default=[], help="table name to snapshot (repeatable)")
ap.add_argument("--every", type=float, default=2.0, help="seconds between snapshots")
ap.add_argument("--times", type=int, default=1, help="number of snapshots")
ap.add_argument("--tail", type=int, default=10, help="rows to print per table")
args = ap.parse_args()

session = Session(host="localhost", port=10000, auth_type="Anonymous")
try:
    for path in args.scripts:
        with open(path, encoding="utf-8") as f:
            t0 = time.perf_counter()
            session.run_script(f.read())
            print(f"ran {path} in {(time.perf_counter() - t0) * 1000:.0f} ms (round trip)")

    for i in range(args.times):
        if args.scripts or i > 0:
            time.sleep(args.every)
        for name in args.show:
            df = session.open_table(name).to_arrow().to_pandas()
            print(f"\n--- {name}: {len(df)} rows (snapshot {i + 1}/{args.times}) ---")
            print(df.tail(args.tail).to_string(index=False))
finally:
    session.close()
