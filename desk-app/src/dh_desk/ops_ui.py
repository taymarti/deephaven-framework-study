"""
The internal ops dashboard, in deephaven.ui. Python's strength here: an operator or analyst view
built in minutes, with no front-end build, rendered by the Deephaven server itself.
Open it at http://<host>:10000/iframe/widget/?name=desk_ops (or the IDE's Panels menu).
The trader-facing app is the React one (dh-desk-web).
"""
from deephaven import ui


@ui.component
def _kpis(risk):
    total = ui.use_memo(lambda: risk.view(["Mv", "DeltaDollars", "VegaDollars"]).sum_by(), [risk])
    breaches = ui.use_memo(lambda: risk.where("Breach").count_by("N"), [risk])
    row = ui.use_row_data(total)
    n = ui.use_cell_data(breaches)
    if row is None:
        return ui.text("waiting for prices")

    def card(label, value, variant="neutral"):
        return ui.view(ui.flex(ui.text(label), ui.heading(value, level=3, margin=0), direction="column"),
                       padding="size-150", border_width="thin", border_color="gray-300", border_radius="medium",
                       background_color="gray-75", flex_grow=1)

    return ui.flex(card("Book market value", f"${row['Mv']:,.0f}"),
                   card("Net delta $", f"${row['DeltaDollars']:,.0f}"),
                   card("Net vega $ / vol pt", f"${row['VegaDollars']:,.0f}"),
                   card("Desks in breach", f"{int(n or 0)}"), gap="size-150", width="100%")


def ops_dashboard(t: dict):
    risk_fmt = [ui.TableFormat(cols=["Mv", "DeltaDollars", "GammaDollars", "VegaDollars", "DeltaLimit"], value="$#,##0"),
                ui.TableFormat(cols="Utilization", value="0.0%", mode=ui.TableDatabar(min=0, max=1.5)),
                ui.TableFormat(cols="Breach", if_="Breach", background_color="negative")]
    book_fmt = [ui.TableFormat(cols=["Spot", "Price"], value="0.00"),
                ui.TableFormat(cols=["Delta", "Gamma", "Vega"], value="0.0000"),
                ui.TableFormat(cols=["Mv", "DeltaDollars", "GammaDollars", "VegaDollars"], value="$#,##0")]
    return ui.dashboard(ui.column(
        ui.row(ui.panel(_kpis(t["risk"]), title="Desk"), height=18),
        ui.row(ui.panel(ui.table(t["risk"], format_=risk_fmt, density="compact"), title="Risk by desk"),
               ui.panel(ui.table(t["limits"], density="compact"), title="Limits (editable)")),
        ui.row(ui.panel(ui.table(t["book"], format_=book_fmt, density="compact"), title="Book (Java-priced)")),
        ui.row(ui.panel(ui.table(t["breach_events"], density="compact"), title="Breach events (Java)"),
               ui.panel(ui.table(t["alerts"], density="compact"), title="Alerts (Python action)"),
               ui.panel(ui.table(t["spot"], density="compact"), title="Spot")),
    ))
