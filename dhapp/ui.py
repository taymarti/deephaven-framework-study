"""
Dashboards from an App with no UI code, and the three building blocks to go further.

    book_dashboard = dashboard(app, kpis={"risk": ["Gross", "PnL"]},
                               formats={"risk": [ui.TableFormat(cols="Utilization", value="0.0%")]})

Open it at http://<host>:10000/iframe/widget/?name=book_dashboard (or the IDE's Panels menu).
The variable must be a global in the worker (application-mode script or console).

Building blocks (all plain deephaven.ui; copy and adapt):
  table_panel(t, title, formats)   a live grid; editable when t is an input table
  kpi_row(t, cols, title)          one card per column of a one-row summary (re-renders on every tick)
  status_panel(app)                mode, runtime, table bindings and action health
"""
from deephaven import ui

from dhfw import runtime


@ui.component
def kpi_row(summary, cols, title: str = ""):
    row = ui.use_row_data(summary)
    if row is None:
        return ui.text(f"{title}: waiting for data")
    cards = [ui.view(ui.flex(ui.text(c), ui.heading(_fmt(row.get(c)), level=3, margin=0), direction="column"),
                     padding="size-150", border_width="thin", border_color="gray-300", border_radius="medium",
                     background_color="gray-75", flex_grow=1) for c in cols]
    return ui.flex(*cards, gap="size-150", width="100%")


def table_panel(t, title: str, formats=None):
    return ui.panel(ui.table(t, format_=formats or [], density="compact"), title=title)


def status_panel(app):
    info = runtime()
    lines = [ui.text(f"App {app.name} · mode {app.mode} · {info['runtime']} {info['core_version']}")]
    for name, s in app._sources.items():
        where = app.catalog.binding(s["catalog"]) if s["catalog"] else ("live factory" if s["live"] and app.mode == "live" else "pushed feed")
        lines.append(ui.text(f"source {name}: {where}"))
    if info.get("warning"):
        lines.append(ui.text(info["warning"]))
    return ui.panel(ui.flex(ui.flex(*lines, direction="column", gap="size-50"),
                            ui.table(app.health, density="compact"), direction="column", gap="size-150"),
                    title="Status")


def dashboard(app, kpis: dict = None, formats: dict = None, per_row: int = 2):
    """One panel per surfaced table, two per row; optional KPI cards over one-row summaries."""
    kpis, formats = kpis or {}, formats or {}
    rows = []
    for name, cols in kpis.items():
        total = app.table(name).view(cols).sum_by()  # numeric KPI columns only
        rows.append(ui.row(ui.panel(kpi_row(total, cols, name), title=f"{name} totals"), height=20))
    panels = [table_panel(app.table(n), n, formats.get(n)) for n in app._surfaces]
    for i in range(0, len(panels), per_row):
        rows.append(ui.row(*panels[i:i + per_row]))
    rows.append(ui.row(status_panel(app), height=22))
    return ui.dashboard(ui.column(*rows))


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    return "-" if v is None else str(v)
