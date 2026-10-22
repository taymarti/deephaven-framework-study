"""
The rung-6 trading and risk engine, rebuilt on dhapp. Compare with 06_trading_engine.py:
the graph is the same, but the wiring, modes, health, publishing and dashboard come free.

    app = make_app(catalog)      # declare; nothing runs yet
    app.start("live")            # or "backtest" / "test"
"""
from dhapp import App, recipes, schemas


class RecordingBroker:
    """Stands in for an order gateway: in sim modes, and here in live too (no real broker)."""
    def __init__(self):
        self.sent = []

    def send(self, rows):
        self.sent.extend(rows[["Sym", "OrderQty", "FillPx"]].itertuples(index=False, name=None))


def make_app(catalog, broker_live=None, broker_sim=None, quotes_history=None, flaky_alert=False):
    app = App("mm", catalog)

    app.source("quotes", schemas.QUOTES, history=quotes_history)   # pushed live; replayed in backtest
    app.source("limits", catalog="desk_limits")                      # wherever the catalog says
    app.source("desks", catalog="desk_map")

    @app.stage
    def orders(quotes):
        return recipes.fill_at_touch(recipes.target_to_orders(recipes.ema_cross(quotes, fast=5, slow=20)))

    @app.stage
    def book(orders, quotes):
        return recipes.mark_to_market(recipes.positions(orders), quotes)

    @app.stage
    def risk(book, desks, limits):
        return recipes.risk_rollup(book, desks, limits)

    @app.action(on="orders", services=["broker"])
    def route(rows, broker):
        broker.send(rows)

    if flaky_alert:  # proves supervision: this action fails on every call and must not stop anything
        @app.action(on="orders")
        def alert(rows):
            raise RuntimeError("alert service down")

    app.service("broker", live=broker_live or RecordingBroker(), sim=broker_sim or RecordingBroker())
    app.surface("book", "risk", "orders", "limits")
    return app
