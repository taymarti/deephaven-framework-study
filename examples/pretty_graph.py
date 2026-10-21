"""
A readable version of perfmon.ancestor_svg: same engine data, friendlier picture.

  * Labels: raw Java descriptions -> plain operations
      "by(NORMAL:[ColumnAggregation{spec=AggSpecWAvg{weight=ColumnName(Qty)}, ...}], [Sym])"
      -> "agg_by Sym:  VWAP = wavg(Px, Qty) · Last = last(Px) · Trades = count"
  * Names: nodes are titled with the Python variable holding that table.
  * Cost: average engine time and invocations per perf interval (~1 min).
  * Flow: arrows point downstream (source -> ... -> callback).
  * Kinds: sources (green), table ops (blue), Python callbacks (orange);
    engine internals (e.g. update_by's partitioning) are collapsed by default.

Run on the server (after rungs 2-4), then e.g.:
  svg = pretty_graph(["ex3 SignalTracker"], title="Rung 3")
  ex_pretty = pretty_graph_image(["ex3 SignalTracker", "ex4 synchronizer"])
"""
import base64
import html
import re
import subprocess

import jpy
from deephaven import agg, perfmon
from deephaven.pandas import to_pandas
from deephaven.table import Table

_BaseTable = jpy.get_type("io.deephaven.engine.table.impl.BaseTable")

_AGG_NAMES = {"First": "first", "Last": "last", "Min": "min", "Max": "max", "Sum": "sum",
              "AbsSum": "abs_sum", "Avg": "avg", "WAvg": "wavg", "WSum": "wsum", "Std": "std",
              "Var": "var", "Median": "median", "CountDistinct": "count_distinct",
              "Distinct": "distinct", "Group": "group"}
_INTERNAL = re.compile(r"TransformFailureListener|validate partitioned|__CONSTITUENT__|Partition\{")


# --- label humanizer -------------------------------------------------------

def _cols(s: str, limit: int = 5) -> str:
    cols = [c.strip() for c in s.split(",") if c.strip()]
    return ", ".join(cols[:limit]) + (f", … +{len(cols) - limit}" if len(cols) > limit else "")


def _parse_aggs(body: str) -> list:
    out = []
    starts = [m.start() for m in re.finditer(r"(?:ColumnAggregations?|Count|Partition)\{", body)]
    for i, s in enumerate(starts):
        chunk = body[s: starts[i + 1] if i + 1 < len(starts) else len(body)]
        if chunk.startswith("Count"):
            m = re.search(r"ColumnName\((\w+)\)", chunk)
            out.append(f"{m.group(1) if m else 'Count'} = count")
            continue
        if chunk.startswith("Partition"):
            out.append("partition")
            continue
        spec = re.search(r"AggSpec(\w+)\{([^}]*)\}", chunk)
        fn = _AGG_NAMES.get(spec.group(1), spec.group(1).lower()) if spec else "agg"
        weight = re.search(r"weight=ColumnName\((\w+)\)", spec.group(2)) if spec else None
        rest = chunk[spec.end():] if spec else chunk
        for inp, outp, same in re.findall(
                r"PairImpl\{input=ColumnName\((\w+)\), output=ColumnName\((\w+)\)\}|ColumnName\((\w+)\)", rest):
            src, dst = (inp, outp) if inp else (same, same)
            arg = f"{src}, {weight.group(1)}" if weight else src
            out.append(f"{dst} = {fn}({arg})" if dst != src else f"{fn}({src})")
    return out


def humanize(desc: str) -> tuple:
    """-> (kind, title, detail). kind in source|op|callback|internal."""
    d = desc.strip()
    if _INTERNAL.search(d) and "SourceListener" not in d:
        return "internal", "engine internal", d[:60]
    if m := re.fullmatch(r"TimeTable\(\w+,(\d+)\)", d):
        return "source", "time_table", f"tick every {int(m.group(1)) / 1e9:g}s"
    if "blinkToAppendOnly" in d:
        return "source", "blink → append-only", "rows pushed from Python (table_publisher)"
    if "UpdateByManager" in d and "SourceListener" in d:
        return "op", "update_by", "rolling / cumulative op, per key"
    if m := re.fullmatch(r"(Update|View|Select|UpdateView|LazyUpdate)\(\[(.*)\]\)", d):
        return "op", m.group(1).lower().replace("updateview", "update_view"), _cols(m.group(2))
    if m := re.fullmatch(r"(naturalJoin|exactJoin|join|aj|raj)\(\[(.*?)\], \[(.*?)\]\)", d):
        name = {"naturalJoin": "natural_join", "exactJoin": "exact_join"}.get(m.group(1), m.group(1))
        return "op", name, f"on {_cols(m.group(2))}  ⟶ adds {_cols(m.group(3))}"
    if m := re.fullmatch(r"where\(\[(.*)\]\)", d):
        return "op", "where", m.group(1)
    if m := re.fullmatch(r"by\(\w+:\[(.*)\], \[(.*?)\]\)", d):
        aggs, keys = _parse_aggs(m.group(1)), m.group(2)
        if aggs == ["partition"]:
            return "internal", "partition", f"by {keys}"
        title = f"agg_by {keys}" if keys else "agg (whole table)"
        return "op", title, " · ".join(aggs)
    if d == "sortInternal":
        return "op", "sort", ""
    if m := re.fullmatch(r"head\(0, (\d+)\)", d):
        return "op", "head", m.group(1)
    if m := re.fullmatch(r"(\w+)\((.*)\)", d):
        return "op", m.group(1), m.group(2)[:60]
    # Anything left with no Java-ish syntax is a listener description we wrote.
    if not re.search(r"[(\[{@]", d):
        return "callback", d, "Python listener"
    return "op", d[:50], ""


# --- graph assembly --------------------------------------------------------

def _var_names(scope: dict) -> dict:
    """perf entry id -> [Python variable names holding the table it produces]."""
    names = {}
    for name, val in scope.items():
        if isinstance(val, Table) and not name.startswith("_") and not name.startswith(("perf_", "ex5_", "probe")):
            try:
                bt = jpy.cast(val.j_table, _BaseTable)
                for eid in bt.parentPerformanceEntryIds().toArray():
                    names.setdefault(int(eid), []).append(name)
            except Exception:  # noqa: BLE001 - static tables etc. have no entry
                pass
    return names


def _snapshot():
    anc = to_pandas(perfmon.update_performance_ancestors_log().where("!isNull(EntryId)"))
    upl = perfmon.update_performance_log().where("!isNull(EntryId)")
    cost = to_pandas(upl.agg_by(
        [agg.sum_(["UsageNanos", "Calls = InvocationCount", "Rows = RowsAdded"]),
         agg.sum_("Mods = RowsModified"), agg.count_("Intervals")], by="EntryId"))
    # Source nodes (no ancestors) are absent from the ancestors log, so take
    # descriptions from the update performance log as well.
    upl_desc = to_pandas(upl.last_by("EntryId").view(["EntryId", "EntryDescription"]))
    desc = {}
    for r in list(upl_desc.itertuples()) + list(anc.itertuples()):
        if isinstance(r.EntryDescription, str):
            desc[int(r.EntryId)] = r.EntryDescription
    parents = {int(r.EntryId): [int(a) for a in (r.Ancestors if r.Ancestors is not None else [])]
               for r in anc.itertuples()}
    costs = {int(r.EntryId): r for r in cost.itertuples()}
    return desc, parents, costs


def _find(desc: dict, root, var_names: dict) -> list:
    if isinstance(root, int):
        return [root]
    by_var = [eid for eid, names in var_names.items() if root in names]
    if by_var:  # a Python variable name holding a table
        return by_var
    exact = [eid for eid, d in desc.items() if d == root]
    # Substring fallback; exact wins so e.g. a where(...contains(`root`)) query
    # used to look the node up doesn't get drawn too.
    return exact or [eid for eid, d in desc.items() if root in d]


def build_dot(roots, title: str = "", scope: dict = None, collapse_internal: bool = True) -> str:
    desc, parents, costs = _snapshot()
    var_names = _var_names(scope if scope is not None else globals())

    # Walk upstream from the roots.
    todo = [e for r in roots for e in _find(desc, r, var_names)]
    nodes, seen = [], set()
    while todo:
        e = todo.pop()
        if e in seen or e not in desc:
            continue
        seen.add(e)
        nodes.append(e)
        todo.extend(parents.get(e, []))

    kinds = {e: humanize(desc[e]) for e in nodes}

    # Collapse internals: connect each internal node's parents to its children.
    def visible_parents(e, stack=()):
        out = []
        for p in parents.get(e, []):
            if p not in seen:
                continue
            if collapse_internal and kinds[p][0] == "internal" and p not in stack:
                out.extend(visible_parents(p, stack + (p,)))
            else:
                out.append(p)
        return sorted(set(out))

    shown = [e for e in nodes if not (collapse_internal and kinds[e][0] == "internal")]
    fill = {"source": "#d9f2d0", "op": "#dbe8f7", "callback": "#fcdcb8", "internal": "#eeeeee"}
    border = {"source": "#3d8b37", "op": "#3a6ea5", "callback": "#c46a0b", "internal": "#999999"}

    lines = ['digraph G {', 'rankdir=TB; nodesep=0.35; ranksep=0.45;',
             'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, margin="0.15,0.07"];',
             'edge [color="#777777", arrowsize=0.7];']
    if title:
        lines.append(f'labelloc=t; fontname="Helvetica"; fontsize=15; label=<<b>{html.escape(title)}</b>>;')
    for e in shown:
        kind, op_title, detail = kinds[e]
        name = ", ".join(var_names.get(e, []))
        rows = []
        if name:
            rows.append(f'<b>{html.escape(name)}</b>')
            rows.append(f'<font color="#333333">{html.escape(op_title)}</font>')
        else:
            rows.append(f'<b>{html.escape(op_title)}</b>')
        for chunk in _wrap(detail, 48):
            rows.append(f'<font point-size="9" color="#444444">{html.escape(chunk)}</font>')
        c = costs.get(e)
        if c is not None and c.Intervals:
            ms = c.UsageNanos / 1e6 / c.Intervals
            rows.append(f'<font point-size="8" color="#777777">{ms:.1f} ms · {c.Calls / c.Intervals:.0f} calls '
                        f'per interval</font>')
        pen = 2 if kind == "callback" else 1
        lines.append(f'n{e} [label=<{"<br/>".join(rows)}>, fillcolor="{fill[kind]}", '
                     f'color="{border[kind]}", penwidth={pen}];')
    for e in shown:
        for p in visible_parents(e):
            lines.append(f"n{p} -> n{e};")
    lines.append('subgraph cluster_legend { label="";  style=invis; '
                 'l1 [label="source", fillcolor="#d9f2d0", color="#3d8b37"]; '
                 'l2 [label="table operation", fillcolor="#dbe8f7", color="#3a6ea5"]; '
                 'l3 [label="Python callback", fillcolor="#fcdcb8", color="#c46a0b", penwidth=2]; '
                 'l1 -> l2 -> l3 [style=invis]; }')
    lines.append("}")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list:
    if not text:
        return []
    out, cur = [], ""
    for part in re.split(r"(?<=[·,])\s+", text):
        if cur and len(cur) + len(part) + 1 > width:
            out.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    return out + ([cur] if cur else [])


def pretty_graph(roots, title: str = "", scope: dict = None, collapse_internal: bool = True) -> str:
    """SVG text for everything upstream of `roots`: table variable names, listener
    descriptions (exact, else substring), or perf entry ids."""
    dot = build_dot(roots, title, scope, collapse_internal)
    return subprocess.run(["dot", "-Tsvg"], input=dot.encode(), capture_output=True, check=True).stdout.decode()


def pretty_graph_image(roots, title: str = "", scope: dict = None):
    """Same graph as a deephaven.ui element, viewable in the IDE / iframe widget URL."""
    from deephaven import ui
    svg = pretty_graph(roots, title, scope)
    return ui.image(src="data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(),
                    alt=title, width="100%", object_fit="contain")
