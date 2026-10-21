"""
Mock market-making book. This is the shared "backend" for BOTH frontends:

  (1) deephaven.ui  -> ui_dashboard.py renders these tables server-side.
  (2) React client  -> fetches these tables by name over the JS API, writes
                       to `risk_limits`, and calls `run_stress` via runCode.

Pipeline (all live / ticking):

  ref_data ─┐
            ├─> trades ─> positions ─> desk_pnl ─┐
  time_table┘                 │                  ├─> desk_risk
                              └─> book_summary   │
                                   risk_limits ──┘  (input table: client-editable)
"""
from deephaven import agg, input_table, new_table, time_table
from deephaven import dtypes as dht
from deephaven.column import double_col, int_col, string_col
from deephaven.table import Table

# Application-mode scripts don't automatically publish into the console's
# global scope. Declaring these global makes them (a) visible to the IDE /
# iframe widget URLs / JS API by name, and (b) callable from runCode.
global ref_data, trades, recent_trades, positions, desk_pnl, risk_limits
global desk_risk, book_summary, DESKS, run_stress, set_limit

# --- Reference data --------------------------------------------------------
_SYMBOLS = [
    # Sym,   Desk,          BasePx, Vol (per-trade noise)
    ("AAPL", "Tech", 228.0, 0.0015),
    ("MSFT", "Tech", 432.0, 0.0012),
    ("NVDA", "Tech", 131.0, 0.0030),
    ("JPM", "Financials", 221.0, 0.0012),
    ("WFC", "Financials", 64.0, 0.0018),
    ("GS", "Financials", 516.0, 0.0015),
    ("XOM", "Energy", 118.0, 0.0012),
    ("CVX", "Energy", 151.0, 0.0014),
]
DESKS = sorted({s[1] for s in _SYMBOLS})

ref_data = new_table([
    int_col("SymIdx", list(range(len(_SYMBOLS)))),
    string_col("Sym", [s[0] for s in _SYMBOLS]),
    string_col("Desk", [s[1] for s in _SYMBOLS]),
    double_col("BasePx", [s[2] for s in _SYMBOLS]),
    double_col("Vol", [s[3] for s in _SYMBOLS]),
])

# --- Mock trade flow (5 fills/sec) -----------------------------------------
# Price = slow sine "market drift" per symbol + per-trade Gaussian noise.
trades = (
    time_table("PT0.2s")
    .update(f"SymIdx = randomInt(0, {len(_SYMBOLS)})")
    .natural_join(ref_data, on="SymIdx")
    .update([
        "Side = randomBool() ? `Buy` : `Sell`",
        "Qty = 100 * randomInt(1, 20)",
        "Price = BasePx * (1 + 0.02 * Math.sin(epochMillis(Timestamp) / 45000.0 + SymIdx)"
        " + randomGaussian(0.0, Vol))",
        "SignedQty = Side == `Buy` ? Qty : -Qty",
        "Notional = SignedQty * Price",
    ])
    .view(["Timestamp", "Desk", "Sym", "Side", "Qty", "Price", "SignedQty", "Notional"])
)
recent_trades = trades.reverse().head(200)

# --- Positions & P&L -------------------------------------------------------
positions = trades.agg_by(
    [
        agg.sum_(["NetQty = SignedQty", "Cost = Notional"]),
        agg.last("Last = Price"),
        agg.count_("Trades"),
    ],
    by=["Desk", "Sym"],
).update(["MktValue = NetQty * Last", "PnL = MktValue - Cost"])

desk_pnl = positions.agg_by(
    [
        agg.sum_(["PnL", "NetMktValue = MktValue", "Trades"]),
        agg.abs_sum("GrossExposure = MktValue"),
    ],
    by="Desk",
)

book_summary = positions.agg_by([
    agg.sum_(["PnL", "Trades"]),
    agg.abs_sum("GrossExposure = MktValue"),
    agg.count_("Positions"),
])

# --- Risk limits: a keyed INPUT table that clients can write to ------------
risk_limits = input_table(
    init_table=new_table([
        string_col("Desk", DESKS),
        double_col("Limit", [15_000_000.0, 10_000_000.0, 20_000_000.0]),  # Energy, Financials, Tech
    ]),
    key_cols="Desk",
)

desk_risk = desk_pnl.natural_join(risk_limits, on="Desk", joins="Limit").update([
    "Utilization = GrossExposure / Limit",
    "Status = Utilization > 1.0 ? `BREACH` : Utilization > 0.8 ? `WARN` : `OK`",
])


# --- "Callbacks": server-side functions the frontends invoke ---------------
def run_stress(shock_pct: float, desk: str | None = None) -> Table:
    """What-if: revalue every position under a uniform price shock (in %).

    Returns a live table - it keeps ticking as the underlying positions move.
    """
    shock = float(shock_pct) / 100.0
    src = positions
    if desk:
        if desk not in DESKS:  # never interpolate untrusted strings into formulas
            raise ValueError(f"unknown desk {desk!r}")
        src = src.where(f"Desk == `{desk}`")
    return src.update([
        f"ShockedPx = Last * (1 + {shock})",
        "StressPnL = NetQty * ShockedPx - Cost",
        "PnLImpact = StressPnL - PnL",
    ]).view(["Desk", "Sym", "NetQty", "Last", "ShockedPx", "PnL", "StressPnL", "PnLImpact"])


def set_limit(desk: str, limit: float) -> None:
    """Upsert a desk's gross-exposure limit (keyed on Desk)."""
    if desk not in DESKS:
        raise ValueError(f"unknown desk {desk!r}")
    risk_limits.add(new_table([string_col("Desk", [desk]), double_col("Limit", [float(limit)])]))
