"""
Rung 2 - The DAG replaces on_data (for derived data).

In your framework, on_data(batch) recomputes VWAPs, last prices and signals in
Python every checkpoint. Here you DECLARE those relationships once; the engine
keeps them true every cycle, updating incrementally (only rows/groups that
changed are recomputed). No user code runs per tick.

  python examples/run.py examples/02_declarative_dag.py --show ex2_signals --every 2 --times 3
"""
from deephaven import agg, time_table
from deephaven.updateby import rolling_avg_tick

# Feed: ~10 trades/sec across 3 symbols.
ex2_trades = time_table("PT0.1s").update([
    "Sym = (ii % 3 == 0) ? `AAPL` : (ii % 3 == 1) ? `MSFT` : `NVDA`",
    "Px = 100 + 5 * Math.sin(ii / 40.0) + randomGaussian(0.0, 0.3)",
    "Qty = 100 * randomInt(1, 10)",
])

# Derived, all live. Each line is a node in the update graph.
ex2_bars = ex2_trades.update("Minute = lowerBin(Timestamp, 'PT1m')").agg_by(
    [agg.first("Open = Px"), agg.max_("High = Px"), agg.min_("Low = Px"), agg.last("Close = Px"),
     agg.sum_("Volume = Qty")],
    by=["Sym", "Minute"],
)
ex2_vwap = ex2_trades.agg_by(
    [agg.weighted_avg("Qty", "VWAP = Px"), agg.last("Last = Px"), agg.count_("Trades")],
    by="Sym",
)
# Moving average over the last 50 trades per symbol, then a signal on top.
ex2_signals = (
    ex2_trades.update_by(rolling_avg_tick("MA50 = Px", rev_ticks=50), by="Sym")
    .last_by("Sym")
    .natural_join(ex2_vwap, on="Sym", joins="VWAP")
    .update(["Signal = MA50 > VWAP ? `LONG` : `SHORT`"])
    .view(["Sym", "Timestamp", "Px", "MA50", "VWAP", "Signal"])
)
