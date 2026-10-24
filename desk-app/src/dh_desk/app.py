"""
The application graph. Python declares it; Java computes the hot parts; React and deephaven.ui
read and write the published tables.

    spot_feed ─last_by─► spot ─┐
    vols (static) ─────────────┼─► book: positions + Java Pricing.price/delta/gamma/vega per row
    tickets (input) ─agg_by─► positions ─┘            │
                                                      ▼ agg_by Desk
    limits (input, keyed) ───────────────────────► risk: DeltaDollars vs DeltaLimit, Breach
                                                      │
                          Java LimitBreachTracker ◄───┘  (stateful, on the update cycle)
                                     │
                              breach_events ─► Python alert action ─► alerts

Published names (the console scope; React opens them by name):
    spot, positions, book, risk, limits, tickets, breach_events, alerts, desk_ops (dashboard)
"""
import logging

import jpy
from deephaven import agg, input_table, new_table
from deephaven import dtypes as dht
from deephaven.column import double_col, long_col, string_col
from deephaven.stream import blink_to_append_only
from deephaven.stream.table_publisher import table_publisher
from deephaven.table import Table
from deephaven.table_listener import listen

from dh_desk.feeds import UNDERLYINGS, SpotFeed

log = logging.getLogger("dh_desk")
RATE = 0.04

TICKET_SCHEMA = {"Desk": dht.string, "Trader": dht.string, "Underlying": dht.string, "Type": dht.string,
                 "Strike": dht.double, "Tenor": dht.double, "Qty": dht.int64}
SEED_TICKETS = [  # Desk, Trader, Underlying, Type, Strike, Tenor (years), Qty (contracts)
    ("Tech", "ana", "AAPL", "C", 190.0, 0.25, 400), ("Tech", "ana", "AAPL", "P", 180.0, 0.25, -250),
    ("Tech", "ben", "MSFT", "C", 420.0, 0.50, 150), ("Tech", "ben", "MSFT", "P", 400.0, 0.50, 120),
    ("Semis", "cai", "NVDA", "C", 120.0, 0.25, 600), ("Semis", "cai", "NVDA", "C", 130.0, 0.50, -300),
    ("Semis", "dee", "NVDA", "P", 110.0, 0.25, 350),
]
SEED_LIMITS = {"Tech": 4_000_000.0, "Semis": 2_500_000.0}  # absolute delta-dollars per desk


def build() -> dict:
    """Build the graph; returns name -> object to publish. Must run on a thread with a real
    execution context (the thread that started the server, as dh_desk.server does)."""
    pricing = "com.acme.desk.Pricing"  # Java, from the bundled jar (fully qualified in formulas)

    feed = SpotFeed().start()
    spot = feed.table.last_by("Underlying")
    vols = new_table([string_col("Underlying", list(UNDERLYINGS)), double_col("Vol", [0.28, 0.24, 0.45])])

    tickets = input_table(TICKET_SCHEMA)  # append-only: every ticket is kept (React's order ticket writes here)
    tickets.add(new_table([string_col("Desk", [t[0] for t in SEED_TICKETS]),
                           string_col("Trader", [t[1] for t in SEED_TICKETS]),
                           string_col("Underlying", [t[2] for t in SEED_TICKETS]),
                           string_col("Type", [t[3] for t in SEED_TICKETS]),
                           double_col("Strike", [t[4] for t in SEED_TICKETS]),
                           double_col("Tenor", [t[5] for t in SEED_TICKETS]),
                           long_col("Qty", [t[6] for t in SEED_TICKETS])]))
    limits = input_table({"Desk": dht.string, "DeltaLimit": dht.double}, key_cols="Desk")  # React edits these
    limits.add(new_table([string_col("Desk", list(SEED_LIMITS)), double_col("DeltaLimit", list(SEED_LIMITS.values()))]))

    positions = tickets.agg_by([agg.sum_("Qty"), agg.count_("Tickets")],
                               by=["Desk", "Underlying", "Type", "Strike", "Tenor"]).where("Qty != 0")

    book = (positions
            .natural_join(spot, on="Underlying", joins="Spot")
            .natural_join(vols, on="Underlying", joins="Vol")
            .update([f"Rate = {RATE}", "IsCall = Type == `C`",
                     f"Price = {pricing}.price(Spot, Strike, Tenor, Vol, Rate, IsCall)",
                     f"Delta = {pricing}.delta(Spot, Strike, Tenor, Vol, Rate, IsCall)",
                     f"Gamma = {pricing}.gamma(Spot, Strike, Tenor, Vol, Rate)",
                     f"Vega = {pricing}.vega(Spot, Strike, Tenor, Vol, Rate)",
                     "Mv = Qty * Price * 100", "DeltaDollars = Qty * Delta * Spot * 100",
                     "GammaDollars = Qty * Gamma * Spot * Spot * 100 / 100", "VegaDollars = Qty * Vega * 100"])
            .drop_columns(["Rate", "IsCall"]))

    risk = (book.agg_by([agg.sum_(["Mv", "DeltaDollars", "GammaDollars", "VegaDollars"]), agg.count_("Positions")], by="Desk")
            .natural_join(limits, on="Desk", joins="DeltaLimit")
            .update(["Utilization = abs(DeltaDollars) / DeltaLimit", "Breach = Utilization > 1.0"]))

    # Java: a stateful listener on the update cycle; keep the reference or it is released.
    tracker = jpy.get_type("com.acme.desk.LimitBreachTracker").attach(risk.j_table)
    breach_events = blink_to_append_only(Table(j_table=tracker.events()))

    # Python: an action on the (rare) breach events. Alerting is I/O-bound: Python's job.
    alerts_blink, alerts_pub = table_publisher("alerts", {"Desk": dht.string, "Message": dht.string})
    alerts = blink_to_append_only(alerts_blink)

    def on_breach(update, is_replay):
        added = update.added()
        desks, events, utils = added.get("Desk", []), added.get("Event", []), added.get("Utilization", [])
        if len(desks) == 0:
            return
        msgs = [f"{d}: {e} at {u:.0%} of its delta limit" for d, e, u in zip(desks, events, utils, strict=True)]
        for m in msgs:
            log.warning("ALERT %s", m)  # a real desk would page, email or post to chat here
        alerts_pub.add(new_table([string_col("Desk", list(desks)), string_col("Message", msgs)]))

    alert_handle = listen(breach_events, on_breach, do_replay=True, description="dh_desk alert action")

    from dh_desk.ops_ui import ops_dashboard
    tables = {"spot": spot, "positions": positions, "book": book, "risk": risk, "limits": limits,
              "tickets": tickets, "breach_events": breach_events, "alerts": alerts}
    return {**tables, "desk_ops": ops_dashboard(tables),
            # held so they are not released; underscore names are published too (harmless)
            "_dh_desk_keepalive": (feed, tracker, alert_handle)}
