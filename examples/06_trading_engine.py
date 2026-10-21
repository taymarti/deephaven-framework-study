"""
Rung 6: a small trading and risk engine, written once as a graph of tables,
then run two ways on the same history:

  live      quotes pushed from a feed thread onto the default ~1 s clock
  backtest  the same quotes stepped through an event-driven graph by our loop

There is no OnData. Signals, orders, fills, positions, P&L and desk risk are all
tables; one listener is the only place Python runs per cycle (order routing).

Run with the server venv (embedded pip server, no client needed):
  .venv-server/Scripts/python examples/06_trading_engine.py
Results go to examples/06_trading_engine.json.
"""
import json
import os
import pathlib
import random
import threading
import time

OUT = pathlib.Path(__file__).with_name("06_trading_engine.json")
SYMS = ["AAPL", "MSFT", "NVDA"]
DESKS = {"AAPL": "Tech", "MSFT": "Tech", "NVDA": "Semis"}


# --------------------------------------------------------------------------
# The engine: sources in, tables out. Nothing here knows live from backtest.
# --------------------------------------------------------------------------
def build_engine(quotes, limits, desks):
    from deephaven import agg
    from deephaven.updateby import delta, ema_tick

    q = quotes.update("Mid = (Bid + Ask) / 2")
    ind = q.update_by([ema_tick(5, "Fast = Mid"), ema_tick(20, "Slow = Mid")], by="Sym")
    sig = ind.update("Target = Fast > Slow ? 100L : -100L")                       # desired position
    orders = sig.update_by(delta("OrderQty = Target"), by="Sym") \
                .update("OrderQty = isNull(OrderQty) ? Target : OrderQty") \
                .where("OrderQty != 0") \
                .update(["FillPx = OrderQty > 0 ? Ask : Bid",                     # cross the spread
                         "Notional = OrderQty * FillPx"])
    positions = orders.agg_by([agg.sum_(["Pos = OrderQty", "Cost = Notional"]), agg.count_("Trades")], by="Sym")
    book = positions.natural_join(q.last_by("Sym"), on="Sym", joins="Mid") \
                    .update(["Mtm = Pos * Mid", "PnL = Mtm - Cost", "Gross = abs(Mtm)"])
    risk = book.natural_join(desks, on="Sym", joins="Desk") \
               .agg_by([agg.sum_(["Gross", "PnL"]), agg.count_("Names")], by="Desk") \
               .natural_join(limits, on="Desk", joins="Limit") \
               .update("Breach = Gross > Limit")
    return {"signals": sig, "orders": orders, "book": book, "risk": risk}


def history(n_slices=150, per_slice=6, seed=7):
    """Deterministic quote history: random walks, a few quotes per symbol per slice."""
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
    if os.name == "nt":  # same workarounds as server/run_server.py
        jh = pathlib.Path(os.environ["JAVA_HOME"])
        for d in (jh / "bin", jh / "bin" / "server"):
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"
            os.add_dll_directory(str(d))
        args += ["-Dweb.storage.layout.directory=layouts", "-Dweb.storage.notebook.directory=notebooks"]
    return args


def main() -> None:
    from deephaven_server import Server
    Server(port=int(os.environ.get("DH_PORT", "10004")), jvm_args=jvm_args()).start()

    import jpy
    from deephaven import dtypes as dht
    from deephaven import input_table, new_table
    from deephaven.column import double_col, string_col
    from deephaven.execution_context import ExecutionContext, get_exec_ctx
    from deephaven.pandas import to_pandas
    from deephaven.stream import blink_to_append_only
    from deephaven.stream.table_publisher import table_publisher
    from deephaven.table_listener import listen
    from deephaven.update_graph import UpdateGraph

    schema = {"Sym": dht.string, "Bid": dht.double, "Ask": dht.double}
    hist = history()
    desks = new_table([string_col("Sym", list(DESKS)), string_col("Desk", list(DESKS.values()))])

    def slice_table(rows):
        return new_table([string_col("Sym", [r[0] for r in rows]), double_col("Bid", [r[1] for r in rows]),
                          double_col("Ask", [r[2] for r in rows])])

    def make_limits():
        lim = input_table({"Desk": dht.string, "Limit": dht.double}, key_cols="Desk")
        lim.add(new_table([string_col("Desk", ["Tech", "Semis"]), double_col("Limit", [15_000.0, 15_000.0])]))
        return lim

    def snapshot(eng):
        book = to_pandas(eng["book"]).sort_values("Sym").round(4)
        risk = to_pandas(eng["risk"]).sort_values("Desk").round(4)
        return {"orders": int(eng["orders"].size), "book": book.to_dict("records"), "risk": risk.to_dict("records")}

    R = {"slices": len(hist), "quotes": sum(len(s) for s in hist)}

    # ---- live: default periodic clock, a feed thread pushing slices ---------
    quotes_blink, pub = table_publisher("live_quotes", schema)
    live = build_engine(blink_to_append_only(quotes_blink), make_limits(), desks)
    routed = []
    h = listen(live["orders"], lambda u, r: routed.append(len(u.added().get("Sym", []))), description="order router")

    def feed():
        for rows in hist:
            pub.add(slice_table(rows))
            time.sleep(0.02)  # ~50 slices per second of wall time
    t0 = time.perf_counter()
    th = threading.Thread(target=feed, name="quote-feed")
    th.start()
    th.join()
    time.sleep(2.5)  # let the last cycle land
    R["live"] = {"wall_seconds": round(time.perf_counter() - t0, 2), "router_calls": len(routed),
                 "orders_routed": sum(routed), **snapshot(live)}
    h.stop()

    # ---- backtest: same build_engine, our clock, as fast as it goes -------
    ug = jpy.get_type("io.deephaven.engine.updategraph.impl.EventDrivenUpdateGraph").newBuilder("backtest").build()
    ctx = ExecutionContext(j_exec_ctx=get_exec_ctx().j_exec_ctx.withUpdateGraph(ug))
    with ctx:
        bt_blink, bt_pub = table_publisher("bt_quotes", schema, update_graph=UpdateGraph(j_update_graph=ug))
        bt_desks = new_table([string_col("Sym", list(DESKS)), string_col("Desk", list(DESKS.values()))])
        bt_limits = new_table([string_col("Desk", ["Tech", "Semis"]), double_col("Limit", [15_000.0, 15_000.0])])
        bt = build_engine(blink_to_append_only(bt_blink), bt_limits, bt_desks)
        bt_routed = []
        bh = listen(bt["orders"], lambda u, r: bt_routed.append(len(u.added().get("Sym", []))))
        t0 = time.perf_counter()
        for rows in hist:
            bt_pub.add(slice_table(rows))
            ug.requestRefresh()  # one checkpoint per slice
        R["backtest"] = {"wall_seconds": round(time.perf_counter() - t0, 3), "router_calls": len(bt_routed),
                         "orders_routed": sum(bt_routed), **snapshot(bt)}
        bh.stop()

    R["same_final_book"] = R["live"]["book"] == R["backtest"]["book"]
    R["same_final_risk"] = R["live"]["risk"] == R["backtest"]["risk"]
    OUT.write_text(json.dumps(R, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in R.items() if k not in ("live", "backtest")}))
    for mode in ("live", "backtest"):
        print(mode, {k: R[mode][k] for k in ("wall_seconds", "router_calls", "orders_routed", "orders")})
    print("risk", R["backtest"]["risk"])
    os._exit(0)


if __name__ == "__main__":
    main()
