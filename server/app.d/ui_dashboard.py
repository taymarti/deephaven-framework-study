"""
Approach (1): deephaven.ui.

Everything here runs in Python on the Deephaven server. The browser only
receives a serialized element tree + table handles over a JSON-RPC message
stream; every callback (slider drag, button press, row click) is a round
trip back into this file. No JS/React code is written by us at all.

View it at:
  IDE (Panels menu):  http://localhost:10000/ide/
  Standalone page:    http://localhost:10000/iframe/widget/?name=book_dashboard
"""
from deephaven import agg, ui
import deephaven.plot.express as dx

global book_dashboard

# --- small presentational components --------------------------------------

def _money(x) -> str:
    return "–" if x is None else f"${x:,.0f}"


@ui.component
def kpi_card(label: str, value: str, variant: str = "neutral"):
    return ui.view(
        ui.flex(
            ui.text(label),
            ui.heading(value, level=3, margin=0),
            ui.badge(variant.upper(), variant=variant) if variant != "neutral" else None,
            direction="column",
            gap="size-50",
        ),
        padding="size-200",
        border_width="thin",
        border_color="gray-300",
        border_radius="medium",
        background_color="gray-75",
        flex_grow=1,
    )


@ui.component
def book_kpis():
    # use_row_data subscribes to the (single-row, ticking) summary; the
    # component re-renders on every tick.
    s = ui.use_row_data(book_summary)
    if s is None:
        return ui.text("Waiting for first trades…")
    pnl = s["PnL"]
    return ui.flex(
        kpi_card("Book P&L", _money(pnl), "positive" if pnl >= 0 else "negative"),
        kpi_card("Gross exposure", _money(s["GrossExposure"])),
        kpi_card("Trades", f"{int(s['Trades']):,}"),  # use_row_data goes via pandas -> floats
        kpi_card("Positions", f"{int(s['Positions'])}"),
        gap="size-200",
        width="100%",
    )


# --- interactive panels ----------------------------------------------------

@ui.component
def desk_risk_table(on_desk_selected):
    return ui.table(
        desk_risk,
        format_=[
            ui.TableFormat(cols=["PnL", "NetMktValue", "GrossExposure", "Limit"], value="$#,##0"),
            ui.TableFormat(cols="Utilization", value="0.0%", mode=ui.TableDatabar(min=0, max=1.2)),
            ui.TableFormat(cols="PnL", if_="PnL < 0", color="negative"),
            ui.TableFormat(cols="PnL", if_="PnL >= 0", color="positive"),
            ui.TableFormat(cols="Status", if_="Status == `BREACH`", background_color="negative"),
            ui.TableFormat(cols="Status", if_="Status == `WARN`", background_color="notice"),
        ],
        always_fetch_columns="Desk",
        on_row_press=lambda row: on_desk_selected(row["Desk"]["value"]),
        density="compact",
    )


@ui.component
def limit_editor(desk, on_desk_selected):
    limit, set_limit_value = ui.use_state(15_000_000.0)

    def apply(_e=None):
        set_limit(desk, limit)  # writes to the risk_limits input table

    return ui.flex(
        ui.picker(*DESKS, label="Desk", selected_key=desk, on_selection_change=on_desk_selected),
        ui.number_field(
            label="Gross limit ($)",
            value=limit,
            on_change=set_limit_value,
            min_value=0,
            step=250_000,
            format_options={"style": "currency", "currency": "USD", "maximumFractionDigits": 0},
        ),
        ui.button("Apply limit", variant="accent", on_press=apply),
        direction="column",
        gap="size-150",
        margin="size-200",
    )


@ui.component
def stress_panel(desk):
    shock, set_shock = ui.use_state(-5)
    # The callback IS just a Python function call; use_memo re-runs it only
    # when the inputs change. The result is a live table.
    result = ui.use_memo(lambda: run_stress(shock, desk), [shock, desk])
    impact_tbl = ui.use_memo(lambda: result.agg_by(agg.sum_("PnLImpact")), [result])
    impact = ui.use_cell_data(impact_tbl)

    return ui.flex(
        ui.flex(
            ui.slider(
                label=f"Price shock (%) — desk: {desk or 'ALL'}",
                min_value=-20,
                max_value=20,
                step=1,
                value=shock,
                on_change=set_shock,
                width="size-4600",
            ),
            kpi_card(
                "Stress P&L impact",
                _money(impact),
                "neutral" if impact is None else ("positive" if impact >= 0 else "negative"),
            ),
            gap="size-300",
            align_items="end",
        ),
        ui.table(
            result,
            format_=[
                ui.TableFormat(cols=["Last", "ShockedPx"], value="0.00"),
                ui.TableFormat(cols=["PnL", "StressPnL", "PnLImpact"], value="$#,##0"),
                ui.TableFormat(cols="PnLImpact", if_="PnLImpact < 0", color="negative"),
            ],
            density="compact",
        ),
        direction="column",
        gap="size-150",
        height="100%",
    )


# --- dashboard layout ------------------------------------------------------

_price_chart = dx.line(trades.tail(2000), x="Timestamp", y="Price", by="Sym", title="Fill prices")


@ui.component
def book_layout():
    # State hoisted to the root so panels can talk to each other:
    # clicking a desk row drives the limit editor AND the stress test.
    desk, set_desk = ui.use_state(DESKS[0])

    return ui.column(
        ui.row(ui.panel(book_kpis(), title="Book"), height=18),
        ui.row(
            ui.panel(desk_risk_table(set_desk), title="Desk risk (click a row)"),
            ui.panel(limit_editor(desk, set_desk), title="Risk limits"),
            height=32,
        ),
        ui.row(
            ui.stack(
                ui.panel(stress_panel(desk), title="Stress test"),
                ui.panel(ui.table(recent_trades, density="compact"), title="Recent trades"),
            ),
            ui.panel(_price_chart, title="Prices"),
        ),
    )


book_dashboard = ui.dashboard(book_layout())
