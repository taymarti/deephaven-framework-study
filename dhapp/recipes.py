"""
Trading and risk recipes: each takes tables and returns a table, built only from
incremental Deephaven operations (no per-row Python), so every result stays live
and costs Java time, not GIL time. Column contracts follow dhapp.schemas.

    quotes -> mid -> ema_cross -> target_to_orders -> fill_at_touch -> positions
           -> mark_to_market -> risk_rollup
"""
from deephaven import agg
from deephaven.updateby import delta, ema_tick


def mid(quotes):
    """Adds Mid and Spread."""
    return quotes.update(["Mid = (Bid + Ask) / 2", "Spread = Ask - Bid"])


def bars(trades, period: str = "PT1m"):
    """OHLCV bars per Sym. period is an ISO duration (PT1m, PT5m, PT1h)."""
    return trades.update(f"Bin = lowerBin(Timestamp, '{period}')") \
                 .agg_by([agg.first("Open = Px"), agg.max_("High = Px"), agg.min_("Low = Px"),
                          agg.last("Close = Px"), agg.sum_("Volume = Qty")], by=["Sym", "Bin"])


def ema_cross(quotes, fast: int = 5, slow: int = 20, size: int = 100, px: str = "Mid"):
    """Target position: +size when the fast EMA of px is above the slow one, else -size."""
    q = quotes if px in [c.name for c in quotes.columns] else mid(quotes)
    return q.update_by([ema_tick(fast, f"Fast = {px}"), ema_tick(slow, f"Slow = {px}")], by="Sym") \
            .update(f"Target = Fast > Slow ? {size}L : -{size}L")


def target_to_orders(signals, target: str = "Target"):
    """Order quantity = change in target per Sym (the first target is an order too); zero changes dropped."""
    return signals.update_by(delta(f"OrderQty = {target}"), by="Sym") \
                  .update(f"OrderQty = isNull(OrderQty) ? {target} : OrderQty") \
                  .where("OrderQty != 0")


def fill_at_touch(orders, fee_bps: float = 0.0):
    """Simulated fills: buys at Ask, sells at Bid, plus a fee in basis points of notional."""
    return orders.update(["FillPx = OrderQty > 0 ? Ask : Bid", "Notional = OrderQty * FillPx",
                          f"Fee = abs(Notional) * {fee_bps} / 10000.0"])


def positions(fills):
    """Net position, cost and trade count per Sym."""
    return fills.agg_by([agg.sum_(["Pos = OrderQty", "Cost = Notional", "Fees = Fee"]), agg.count_("Trades")], by="Sym")


def mark_to_market(positions_t, quotes, px: str = "Mid"):
    """Joins the latest price per Sym; adds Mtm, PnL (after fees) and Gross."""
    q = quotes if px in [c.name for c in quotes.columns] else mid(quotes)
    return positions_t.natural_join(q.last_by("Sym"), on="Sym", joins=px) \
                      .update([f"Mtm = Pos * {px}", "PnL = Mtm - Cost - Fees", "Gross = abs(Mtm)"])


def risk_rollup(book, desks, limits):
    """Gross and PnL per Desk against its Limit; Breach and Utilization flags."""
    return book.natural_join(desks, on="Sym", joins="Desk") \
               .agg_by([agg.sum_(["Gross", "PnL"]), agg.count_("Names")], by="Desk") \
               .natural_join(limits, on="Desk", joins="Limit") \
               .update(["Utilization = Gross / Limit", "Breach = Gross > Limit"])
