"""
Rung 7: the same engine on dhapp, run three ways, plus catalog and storage checks.

  backtest  the app replays history (one checkpoint per second of data)
  live      a feed thread pushes the same quotes onto the default clock
  test      we push rows, step, and assert; a deliberately failing action is supervised

Run with the server venv:  .venv-server/Scripts/python examples/07_app_framework.py
Results: examples/07_app_framework.json
"""
import importlib.util
import json
import os
import pathlib
import random
import sys
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
OUT = HERE / "07_app_framework.json"
WORK = pathlib.Path(tempfile.mkdtemp(prefix="dhapp_"))
os.environ.update({"DHFW_DATA_ROOT": str(WORK / "data"), "DHFW_PQ_MAP": json.dumps({"RiskLimits": "self"}),
                   "DHFW_PLANT": "ny", "DHFW_PQ": "MarketMaking"})
SYMS = ["AAPL", "MSFT", "NVDA"]
R = {}


def history_rows(n_slices=150, per_slice=6, seed=7):  # same random walk as rung 6
    rnd, px, out = random.Random(seed), {s: 100.0 for s in SYMS}, []
    for _ in range(n_slices):
        rows = []
        for _ in range(per_slice):
            s = rnd.choice(SYMS)
            px[s] += rnd.gauss(0, 0.2)
            rows.append((s, round(px[s] - 0.01, 4), round(px[s] + 0.01, 4)))
        out.append(rows)
    return out


def jvm_args() -> list:
    args = ["-Xmx1g", "-DAuthHandlers=io.deephaven.auth.AnonymousAuthenticationHandler"]
    if os.name == "nt":
        jh = pathlib.Path(os.environ["JAVA_HOME"])
        for d in (jh / "bin", jh / "bin" / "server"):
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"
            os.add_dll_directory(str(d))
        args += ["-Dweb.storage.layout.directory=layouts", "-Dweb.storage.notebook.directory=notebooks"]
    return args


def check(name, fn):
    try:
        R[name] = {"ok": True, "result": fn()}
        print("PASS", name, json.dumps(R[name]["result"], default=str)[:400], flush=True)
    except Exception as e:  # noqa: BLE001
        import traceback
        R[name] = {"ok": False, "error": traceback.format_exc()[-1500:]}
        print("FAIL", name, R[name]["error"], flush=True)


def main() -> None:
    from deephaven_server import Server
    Server(port=int(os.environ.get("DH_PORT", "10006")), jvm_args=jvm_args()).start()

    import __main__
    from deephaven import new_table
    from deephaven.column import datetime_col, double_col, string_col
    from deephaven.pandas import to_pandas
    from dhapp import Catalog, schemas, store
    from mm_app import RecordingBroker, make_app

    T0 = 1_792_000_000_000_000_000
    hist = history_rows()

    def slice_table(i, rows):
        import numpy as np
        ts = [np.datetime64(T0 + i * 1_000_000_000 + j * 1_000_000, "ns") for j in range(len(rows))]
        return new_table([datetime_col("Timestamp", ts), string_col("Sym", [r[0] for r in rows]),
                          double_col("Bid", [r[1] for r in rows]), double_col("Ask", [r[2] for r in rows])])

    from deephaven import merge
    history_table = merge([slice_table(i, rows) for i, rows in enumerate(hist)])

    # The limits live in "another PQ" (RiskLimits); here a state table published as a global stands in for it.
    limits = store.state_table("Risk", "DeskLimits", new_table([string_col("Desk", ["x"]), double_col("Limit", [0.0])]), ["Desk"])
    limits.add(new_table([string_col("Desk", ["Tech", "Semis"]), double_col("Limit", [15_000.0, 15_000.0])]))
    __main__.desk_limits = limits
    time.sleep(1.2)

    def make_catalog():
        c = Catalog({"desk_limits": {"pq": "RiskLimits", "table": "desk_limits", "plant": "ny"},
                     "desk_map": {"db": ["Ref", "DeskMap"], "live": False}})
        c.override("desk_map", new_table([string_col("Sym", SYMS), string_col("Desk", ["Tech", "Tech", "Semis"])]))
        return c

    def snap(app):
        return {"orders": app.table("orders").size,
                "book": to_pandas(app.table("book")).sort_values("Sym").round(4).to_dict("records"),
                "risk": to_pandas(app.table("risk")).sort_values("Desk").round(4)[["Desk", "Gross", "PnL", "Names", "Limit", "Breach"]].to_dict("records")}

    def backtest():
        sim = RecordingBroker()
        app = make_app(make_catalog(), broker_sim=sim, quotes_history=lambda: history_table).start("backtest")
        run = app.run_history(bucket_ms=1000)
        R["_bt"] = snap(app)
        return {**run, "orders": R["_bt"]["orders"], "broker_sent": len(sim.sent), "risk": R["_bt"]["risk"]}
    check("1_backtest_mode", backtest)

    def live():
        broker = RecordingBroker()
        app = make_app(make_catalog(), broker_live=broker).start("live")

        def feed():
            for i, rows in enumerate(hist):
                app.feed("quotes", slice_table(i, rows))
                time.sleep(0.02)
        th = threading.Thread(target=feed, name="quote-feed")
        t0 = time.perf_counter()
        th.start(); th.join()
        time.sleep(2.5)
        R["_live"] = snap(app)
        health = to_pandas(app.health).to_dict("records")
        app.stop()
        return {"seconds": round(time.perf_counter() - t0, 2), "orders": R["_live"]["orders"],
                "broker_sent": len(broker.sent), "health": health,
                "published_fields": sorted(n for n in dir(__main__) if n.startswith("mm_"))}
    check("2_live_mode", live)

    check("3_live_equals_backtest", lambda: {"book": R["_live"]["book"] == R["_bt"]["book"],
                                             "risk": R["_live"]["risk"] == R["_bt"]["risk"]})

    def matches_rung6():
        r6 = json.loads((HERE / "06_trading_engine.json").read_text())["backtest"]["risk"]
        mine = R["_bt"]["risk"]
        same = all(abs(a["Gross"] - b["Gross"]) < 1e-6 and abs(a["PnL"] - b["PnL"]) < 1e-6 and a["Desk"] == b["Desk"]
                   for a, b in zip(sorted(r6, key=lambda x: x["Desk"]), mine))
        assert same, (r6, mine)
        return {"same_risk_as_hand_written_rung6": same}
    check("4_same_numbers_as_rung6", matches_rung6)

    def test_mode():
        app = make_app(make_catalog(), flaky_alert=True).start("test")
        app.feed("quotes", slice_table(0, [("AAPL", 99.99, 100.01)]))
        app.step()
        first = app.table("orders").size                 # the first target is an order
        app.feed("quotes", slice_table(1, [("AAPL", 99.99, 100.01)]))
        app.step()
        same_target = app.table("orders").size           # unchanged target -> no new order
        app.step()                                        # health rows land on the next step
        health = to_pandas(app.health).sort_values("Action").to_dict("records")
        assert first == 1 and same_target == 1, (first, same_target)
        alert = next(h for h in health if h["Action"] == "alert")
        route = next(h for h in health if h["Action"] == "route")
        assert alert["Errors"] == alert["Calls"] == 1 and route["Errors"] == 0 and route["Calls"] == 1, health
        return {"orders_after_step1": first, "orders_after_step2": same_target, "health": health}
    check("5_test_mode_and_supervision", test_mode)

    def catalog_bindings():
        c = make_catalog()
        out = {"here=MarketMaking@ny": c.binding("desk_limits")}
        os.environ["DHFW_PQ"] = "RiskLimits"
        out["here=RiskLimits@ny (deployed into the owner)"] = c.binding("desk_limits")
        os.environ.update({"DHFW_PQ": "MarketMaking", "DHFW_PLANT": "ldn"})
        out["here=MarketMaking@ldn (another plant)"] = c.binding("desk_limits")
        os.environ["DHFW_PLANT"] = "ny"
        out["db entry"] = Catalog({"q": {"db": ["MarketUs", "QuoteStock"]}}).binding("q")
        assert out["here=RiskLimits@ny (deployed into the owner)"].startswith("local global")
        return out
    check("6_catalog_location_transparency", catalog_bindings)

    def storage():
        risk = new_table([string_col("Desk", ["Tech"]), double_col("Gross", [20_832.68])])
        store.snapshot(risk, "Risk", "EodSnapshot")
        store.daily_partition(risk, "Risk", "DailyRisk", date="2026-10-20")
        store.daily_partition(risk, "Risk", "DailyRisk", date="2026-10-21")
        from dhfw import db
        return {"snapshot_rows": db.historical_table("Risk", "EodSnapshot").size,
                "daily_rows": db.historical_table("Risk", "DailyRisk").size,
                "state_table_rows": limits.size}
    check("7_storage_recipes", storage)

    def dashboard():
        from dhapp.ui import dashboard as build
        app = make_app(make_catalog()).start("live")
        d = build(app, kpis={"risk": ["Gross", "PnL"]})
        app.stop()
        return type(d).__name__
    check("8_dashboard_builds", dashboard)

    R.pop("_bt"); R.pop("_live")
    R["summary"] = f"{sum(v['ok'] for v in R.values())}/{len(R)} passed"
    OUT.write_text(json.dumps(R, indent=2, default=str), encoding="utf-8")
    print(R["summary"])
    os._exit(0)


if __name__ == "__main__":
    main()
