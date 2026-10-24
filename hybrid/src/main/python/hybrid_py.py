"""
The Python entry point: rung 2's graph declared in Python, with the two slow-in-Python
nodes swapped for Java from the project's jar:

  * the per-row score:   a Java static call in the formula instead of a Python UDF
  * the flip listener:   SignalFlipTracker (Java) instead of rung 3's Python SignalTracker

Everything else is ordinary Python Deephaven code. Started by hybrid/run.py --entry python.
"""
import jpy
from deephaven import agg, time_table
from deephaven.stream import blink_to_append_only
from deephaven.table import Table
from deephaven.updateby import rolling_avg_tick

SignalFlipTracker = jpy.get_type("com.acme.hybrid.SignalFlipTracker")

hy_trades = time_table("PT0.1s").update([
    "Sym = (ii % 3 == 0) ? `AAPL` : (ii % 3 == 1) ? `MSFT` : `NVDA`",
    "Px = 100 + 5 * Math.sin(ii / 40.0) + randomGaussian(0.0, 0.3)",
    "Qty = 100 * randomInt(1, 10)",
])
_vwap = hy_trades.agg_by([agg.weighted_avg("Qty", "VWAP = Px"), agg.last("Last = Px"), agg.count_("Trades")], by="Sym")
hy_signals = (
    hy_trades.update_by(rolling_avg_tick("MA50 = Px", rev_ticks=50), by="Sym")
    .last_by("Sym")
    .natural_join(_vwap, on="Sym", joins="VWAP")
    .update(["Signal = MA50 > VWAP ? `LONG` : `SHORT`",
             "Score = com.acme.hybrid.Fast.score(Px, MA50, VWAP)"])      # Java, not a Python UDF
    .view(["Sym", "Timestamp", "Px", "MA50", "VWAP", "Signal", "Score"])
)

# The Java listener; keep the reference (a released listener stops).
_hy_tracker = SignalFlipTracker.attach(hy_signals.j_table)
hy_flips = blink_to_append_only(Table(j_table=_hy_tracker.flips()))
