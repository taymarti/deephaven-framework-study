"""
Application-mode script: the dhapp market-making app, live, with a synthetic quote
feed and an auto-built dashboard. Start from the repo root:

  .venv-server/Scripts/python server/run_server.py --app-dir examples/mm_app.d

Open http://localhost:10000/iframe/widget/?name=mm_dashboard
"""
import json
import os
import pathlib
import random
import sys
import threading
import time

ROOT = pathlib.Path.cwd()
sys.path[:0] = [str(ROOT), str(ROOT / "examples")]
os.environ.setdefault("DHFW_PQ_MAP", json.dumps({"RiskLimits": "self"}))
os.environ.setdefault("DHFW_PLANT", "ny")
os.environ.setdefault("DHFW_PQ", "MarketMaking")

import numpy as np  # noqa: E402
from deephaven import new_table, ui  # noqa: E402
from deephaven.column import datetime_col, double_col, string_col  # noqa: E402

from dhapp import Catalog, store  # noqa: E402
from dhapp.ui import dashboard  # noqa: E402
from mm_app import make_app  # noqa: E402

SYMS = ["AAPL", "MSFT", "NVDA"]

# "Another PQ's" editable limits: a state table; edit it from the grid or with .add()
desk_limits = store.state_table("Risk", "DeskLimits", new_table([string_col("Desk", ["x"]), double_col("Limit", [0.0])]), ["Desk"])
desk_limits.add(new_table([string_col("Desk", ["Tech", "Semis"]), double_col("Limit", [15_000.0, 15_000.0])]))

catalog = Catalog({"desk_limits": {"pq": "RiskLimits", "table": "desk_limits", "plant": "ny"},
                   "desk_map": {"db": ["Ref", "DeskMap"], "live": False}})
catalog.override("desk_map", new_table([string_col("Sym", SYMS), string_col("Desk", ["Tech", "Tech", "Semis"])]))

mm = make_app(catalog).start("live")


def _feed(stop=threading.Event()):
    rnd, px = random.Random(7), {s: 100.0 for s in SYMS}
    while not stop.is_set():
        s = rnd.choice(SYMS)
        px[s] += rnd.gauss(0, 0.2)
        mm.feed("quotes", new_table([datetime_col("Timestamp", [np.datetime64(time.time_ns(), "ns")]),
                                     string_col("Sym", [s]), double_col("Bid", [px[s] - 0.01]),
                                     double_col("Ask", [px[s] + 0.01])]))
        time.sleep(0.05)


threading.Thread(target=_feed, name="mm-quote-feed", daemon=True).start()

mm_dashboard = dashboard(
    mm,
    kpis={"risk": ["Gross", "PnL"]},
    formats={"risk": [ui.TableFormat(cols=["Gross", "PnL", "Limit"], value="$#,##0"),
                      ui.TableFormat(cols="Utilization", value="0.0%", mode=ui.TableDatabar(min=0, max=1.5)),
                      ui.TableFormat(cols="Breach", if_="Breach", background_color="negative")],
             "book": [ui.TableFormat(cols=["Mtm", "PnL", "Cost", "Gross"], value="$#,##0.00")]},
)
