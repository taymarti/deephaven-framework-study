"""
dh_introspect - inventory a running Deephaven application from inside its worker.

A Deephaven "application" is whatever a worker has built and kept alive:
named objects in scope (tables, UI components, figures, ...), the update
graph those objects sit in, the sources feeding it, the listeners and sinks
hanging off it, and whatever non-Deephaven machinery (threads, sockets,
libraries) the scripts started alongside. This module reports all of that.

Use it either way:
  * Console / IDE:  paste this file, then  `rep = introspect(); print(render_text(rep))`
  * Any client:     see dh_introspect_client.py (sends this file via run_script,
                    then reads the published report table back)

Side effects (all small, all opt-out):
  * Opens the engine's performance logs (perfmon). Idempotent and cheap.
    NOTE: graph ANCESTRY is only recorded for nodes created after the
    ancestors log was first opened. For full graphs, open
    perfmon.update_performance_ancestors_log() at worker start.
  * publish=True binds a few `dhi_*` tables in the global scope (and a
    one-row `dhi_report` JSON table that clients read). publish=False binds nothing.

Everything Deephaven-specific is imported lazily, so render_text() also works
locally on a JSON report fetched by a client.

Facts this module relies on (verified on Community 42.6; see VERIFIED_FACTS.md):
  * Console commands, run_script/runCode AND application-mode scripts all run in
    one global scope (__main__); with the pip server that is the launcher's own
    __main__. Every exportable object bound there is a `scope` field, including
    underscore-prefixed names, so the exports section reports those too.
  * Execution contexts are per thread. Run this module through run_script or on
    the thread that started the server; elsewhere get_exec_ctx() is static-only.
  * A worker can run more than one update graph (e.g. an event-driven one that
    advances only on requestRefresh()); the graph section lists every graph
    that has performance entries.
"""
from __future__ import annotations

import inspect
import json
import re
import sys
import threading
import time
from collections import Counter, defaultdict

__all__ = ["introspect", "render_text", "PRIMITIVES"]

# What a worker can hand to a client, by server "object type" (the type a client
# sees when it lists fields). Plugins can register more; deephaven.ui and
# plotly-express are themselves plugins.
PRIMITIVES = {
    "Table": "live or static table (incl. input tables, blink tables, pandas DataFrames served as tables)",
    "PartitionedTable": "a table of tables, keyed by partition columns",
    "HierarchicalTable": "tree or rollup table",
    "Figure": "built-in deephaven.plot figure",
    "deephaven.plot.express.DeephavenFigure": "plotly-express figure (plugin)",
    "deephaven.ui.Element": "deephaven.ui component (plugin; rendered server-side, bidirectional)",
    "deephaven.ui.Dashboard": "deephaven.ui dashboard (plugin)",
    "matplotlib.figure.Figure": "matplotlib figure (plugin)",
    "<custom plugin type>": "any registered object type: a message-stream object a JS plugin renders",
}

_PERF_COLS = ("EntryDescription", "UsageNanos", "IntervalStartTime", "IntervalEndTime", "EntryId",
              "UpdateGraph", "IntervalDurationNanos", "Ancestors")
# Engine-internal helper nodes (verified on 42.6): update_by partitions/buckets,
# the two sides of a join, and the per-input "recorder" a merged_listen creates.
_INTERNAL = re.compile(r"TransformFailureListener|validate partitioned|__CONSTITUENT__|Partition\{"
                       r"|UpdateByManager@\w+-bucket(-\[.*\])?$|^(leftTable|rightTable): |Python Wrapped Listener recorder")
# A bare camelCase word (e.g. sortInternal) is an engine operation, not a listener description.
_BARE_OP = re.compile(r"^[a-z]+[A-Z]\w*$")


# ----------------------------------------------------------------------------
# public entry point
# ----------------------------------------------------------------------------

def introspect(scope: dict | None = None, publish: bool = True, include_private: bool = False,
               recent_intervals: int = 5) -> dict:
    """Build the report. `scope` defaults to the console's global scope."""
    scope = _default_scope(scope)
    started = time.time()
    rep: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "errors": []}

    rep["exports"] = _guard(rep, "exports", lambda: _exports(scope, include_private), [])
    rep["graph"] = _guard(rep, "graph", lambda: _graph(rep["exports"], recent_intervals), {})
    rep["inputs"] = _guard(rep, "inputs", lambda: _inputs(rep), [])
    rep["listeners"] = _guard(rep, "listeners", lambda: _listeners(rep, scope), {})
    rep["outputs"] = _guard(rep, "outputs", lambda: _outputs(rep), [])
    rep["runtime"] = _guard(rep, "runtime", _runtime, {})
    rep["findings"] = _guard(rep, "findings", lambda: _findings(rep), [])
    rep["elapsed_ms"] = round((time.time() - started) * 1000)

    if publish:
        _guard(rep, "publish", lambda: _publish(rep, scope), None)
    return rep


# ----------------------------------------------------------------------------
# exports: what is named in scope, and what kind of thing it is
# ----------------------------------------------------------------------------

def _exports(scope: dict, include_private: bool) -> list:
    import jpy
    from deephaven.table import Table, PartitionedTable

    base_table = jpy.get_type("io.deephaven.engine.table.impl.BaseTable")
    optional = _optional_types()
    out = []
    exportable = (Table, PartitionedTable) + tuple(t for k in ("hierarchical", "figure") for t in optional.get(k, ()))
    for name, val in list(scope.items()):
        if name.startswith("dhi_") or name in ("__builtins__", "_dhi_ns"):
            continue
        if inspect.ismodule(val) or inspect.isclass(val):
            continue
        # Underscore names that hold exportable objects ARE published as fields,
        # so always report them; other underscore names only on request.
        if name.startswith("_") and not include_private and not (
                isinstance(val, exportable) or type(val).__module__.startswith(("deephaven.ui", "deephaven.plot"))):
            continue
        rec = {"name": name, "py_type": f"{type(val).__module__}.{type(val).__qualname__}",
               "underscore": name.startswith("_")}
        try:
            if isinstance(val, Table):
                rec.update(_describe_table(val, base_table))
            elif isinstance(val, PartitionedTable):
                rec.update(kind="partitioned_table", refreshing=bool(val.is_refreshing),
                           keys=list(val.key_columns), constituents=_safe(lambda: val.table.size))
            elif any(isinstance(val, t) for t in optional.get("hierarchical", ())):
                rec.update(kind="hierarchical_table")
            elif any(isinstance(val, t) for t in optional.get("listener_handle", ())):
                rec.update(kind="listener_handle", started=getattr(val, "started", None),
                           description=_handle_description(val))
            elif any(isinstance(val, t) for t in optional.get("publisher", ())):
                rec.update(kind="table_publisher")
            elif any(isinstance(val, t) for t in optional.get("figure", ())):
                rec.update(kind="figure")
            elif type(val).__module__.startswith("deephaven.ui"):
                rec.update(kind="ui_element", ui_type=type(val).__name__,
                           component=getattr(getattr(val, "_render", None), "__name__", None)
                           or getattr(val, "name", None))
            elif type(val).__module__.startswith("deephaven.plot"):
                rec.update(kind="figure")
            elif type(val).__module__.startswith("pandas"):
                rec.update(kind="dataframe", rows=_safe(lambda: len(val)))
            elif isinstance(val, threading.Thread):
                rec.update(kind="thread", alive=val.is_alive(), daemon=val.daemon)
            elif isinstance(val, threading.Event):
                rec.update(kind="event", is_set=val.is_set())
            elif inspect.isfunction(val) or inspect.isbuiltin(val):
                if getattr(val, "__module__", None) not in ("__main__", None):
                    continue  # imported library function (e.g. time_table), not part of the app
                rec.update(kind="callable", signature=_safe(lambda: str(inspect.signature(val))),
                           defined_in=getattr(val, "__module__", None))
            elif callable(val):
                rec.update(kind="callable_object")
            else:
                rec.update(kind="python_object", repr=_short(repr(val), 80))
        except Exception as e:  # noqa: BLE001 - one odd object must not sink the report
            rec.update(kind="unknown", error=repr(e))
        out.append(rec)
    return sorted(out, key=lambda r: (r.get("kind", ""), r["name"]))


def _describe_table(t, base_table) -> dict:
    import jpy
    j = t.j_table
    attrs = sorted(str(k) for k in j.getAttributes().keySet().toArray())
    rec = {
        "kind": "table",
        "refreshing": bool(t.is_refreshing),
        "blink": bool(_safe(lambda: t.is_blink, False)),
        "rows": _safe(lambda: int(t.size)),
        "columns": len(t.columns),
        "java_class": j.getClass().getSimpleName(),
        "attributes": attrs,
        "entry_ids": [],
    }
    if "InputTable" in attrs:
        rec["kind"] = "input_table"
    elif not rec["refreshing"]:
        rec["kind"] = "static_table"
    try:
        bt = jpy.cast(j, base_table)
        rec["entry_ids"] = [int(x) for x in bt.parentPerformanceEntryIds().toArray()]
    except Exception:  # noqa: BLE001 - non-BaseTable implementations
        pass
    return rec


def _optional_types() -> dict:
    out: dict = defaultdict(tuple)
    for key, mod, names in [
        ("hierarchical", "deephaven.table", ("TreeTable", "RollupTable")),
        ("listener_handle", "deephaven.table_listener", ("TableListenerHandle", "MergedListenerHandle")),
        ("publisher", "deephaven.stream.table_publisher", ("TablePublisher",)),
        ("figure", "deephaven.plot.figure", ("Figure",)),
    ]:
        try:
            m = __import__(mod, fromlist=list(names))
            out[key] = tuple(getattr(m, n) for n in names if hasattr(m, n))
        except Exception:  # noqa: BLE001
            pass
    return out


def _handle_description(h):
    for attr in ("description", "_description"):
        if isinstance(getattr(h, attr, None), str):
            return getattr(h, attr)
    listener = getattr(h, "listener", None)
    return getattr(listener, "description", None)


# ----------------------------------------------------------------------------
# graph: every engine node, its ancestry, its recent cost
# ----------------------------------------------------------------------------

def _graph(exports: list, recent_intervals: int) -> dict:
    from deephaven import perfmon
    from deephaven.pandas import to_pandas

    upl = perfmon.update_performance_log().where("!isNull(EntryId)")
    anc = perfmon.update_performance_ancestors_log().where("!isNull(EntryId)")
    upl_df = to_pandas(upl.view(["EntryId", "EntryDescription", "IntervalEndTime", "UsageNanos",
                                 "InvocationCount", "RowsAdded", "RowsModified", "RowsRemoved", "UpdateGraph"]))
    anc_df = to_pandas(anc.view(["EntryId", "EntryDescription", "Ancestors"]))

    desc, parents = {}, {}
    for r in upl_df.drop_duplicates("EntryId", keep="last").itertuples():
        if isinstance(r.EntryDescription, str):
            desc[int(r.EntryId)] = r.EntryDescription
    for r in anc_df.itertuples():
        if isinstance(r.EntryDescription, str):
            desc[int(r.EntryId)] = r.EntryDescription
        parents[int(r.EntryId)] = [int(a) for a in (r.Ancestors if r.Ancestors is not None else [])]

    # recent cost per node, and whether it is still being logged ("active")
    gmax = upl_df["IntervalEndTime"].max() if len(upl_df) else None
    stats = {}
    for eid, g in upl_df.groupby("EntryId"):
        tail = g.tail(recent_intervals)
        last_seen = g["IntervalEndTime"].max()
        ug_names = g["UpdateGraph"].dropna()
        stats[int(eid)] = {
            "update_graph": str(ug_names.iloc[-1]) if len(ug_names) else None,
            "ms_per_interval": round(float(tail["UsageNanos"].mean()) / 1e6, 2),
            "calls_per_interval": round(float(tail["InvocationCount"].mean()), 1),
            "rows_changed_per_interval": round(float((tail["RowsAdded"] + tail["RowsModified"]
                                                      + tail["RowsRemoved"]).mean()), 1),
            "active": bool(gmax is not None and (gmax - last_seen).total_seconds() <= 90),
        }

    var_of = defaultdict(list)
    for e in exports:
        for eid in e.get("entry_ids", []):
            var_of[eid].append(e["name"])

    children = defaultdict(list)
    for e, ps in parents.items():
        for p in ps:
            children[p].append(e)

    nodes = []
    for eid, d in desc.items():
        if _is_perf_node(d):
            continue
        kind, label = _classify_node(d)
        s = stats.get(eid, {})
        nodes.append({
            "id": eid, "description": _short(d, 160), "kind": kind, "label": label,
            "variables": var_of.get(eid, []), "parents": parents.get(eid, []),
            "children": [c for c in children.get(eid, []) if c in desc and not _is_perf_node(desc[c])],
            **s,
        })
    ids = {n["id"] for n in nodes}
    for n in nodes:
        n["parents"] = [p for p in n["parents"] if p in ids]

    # Reachability: everything upstream of a named variable or a Python callback.
    by_id = {n["id"]: n for n in nodes}
    roots = [n["id"] for n in nodes if n["variables"] or n["kind"] == "callback"]
    reach, todo = set(), list(roots)
    while todo:
        e = todo.pop()
        if e in reach or e not in by_id:
            continue
        reach.add(e)
        todo.extend(by_id[e]["parents"])
    for n in nodes:
        n["reachable_from_scope"] = n["id"] in reach

    # Ancestry is missing when operations/listeners (which always have inputs)
    # show no parents: that happens for nodes created before the log was opened.
    derived = [n for n in nodes if n.get("active") and n["kind"] in ("op", "callback", "sink")]
    orphaned = sum(1 for n in derived if not n["parents"])
    return {
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "edges": [[p, n["id"]] for n in nodes for p in n["parents"]],
        "ancestry_complete": orphaned <= 0.2 * max(len(derived), 1),
        "derived_nodes_without_parents": orphaned,
        # Every update graph with performance entries: the default periodic one,
        # plus any extra (for example event-driven) graphs the app created.
        "update_graphs": sorted({n["update_graph"] for n in nodes if n.get("update_graph")}),
        "interval_count": int(upl_df["IntervalEndTime"].nunique()) if len(upl_df) else 0,
    }


def _is_perf_node(d: str) -> bool:
    return any(c in d for c in _PERF_COLS) or "PerformanceLog" in d or "ServerState" in d


def _classify_node(d: str) -> tuple:
    """-> (kind, plain label). kind: source | op | callback | sink | internal."""
    if _INTERNAL.search(d) and "SourceListener" not in d:
        return "internal", "engine internal"
    if m := re.fullmatch(r"TimeTable\(\w+,(\d+)\)", d):
        return "source", f"time_table every {int(m.group(1)) / 1e9:g}s"
    if "blinkToAppendOnly" in d:
        # Its upstream (a table_publisher / stream adapter) is not a perf entry, so
        # this adapter is the visible source of a feed pushed from Python.
        return "source", "stream feed (table_publisher / blink -> append-only)"
    if re.search(r"Kafka|kafka", d):
        return ("sink", "Kafka producer") if re.search(r"[Pp]roduc|[Pp]ublish", d) else ("source", "Kafka consumer")
    if re.search(r"Barrage|Remote|Subscription|URI", d):
        return "source", "remote subscription (another worker/server)"
    if re.search(r"StreamToBlink|TablePublisher|StreamPublisher", d):
        return "source", "stream / table_publisher"
    if re.search(r"Parquet|Csv|CSV|Writer|Persist", d):
        return "sink", "writer / persistence"
    if "UpdateByManager" in d and "SourceListener" in d:
        return "op", "update_by"
    if m := re.fullmatch(r"(\w+)\(.*", d):
        return "op", m.group(1)
    if _BARE_OP.fullmatch(d):
        return "op", d
    if not re.search(r"[(\[{@]", d):
        return "callback", "Python listener"
    return "op", _short(d, 40)


# ----------------------------------------------------------------------------
# inputs, listeners, outputs
# ----------------------------------------------------------------------------

def _inputs(rep: dict) -> list:
    out = []
    for n in rep["graph"].get("nodes", []):
        if n["kind"] == "source" or (not n["parents"] and n["kind"] not in ("callback", "internal")):
            out.append({"via": "graph", "id": n["id"], "label": n["label"], "description": n["description"],
                        "variables": n["variables"], "active": n.get("active")})
    for e in rep["exports"]:
        if e.get("kind") == "input_table":
            out.append({"via": "scope", "label": "input table (written by clients / code)", "variables": [e["name"]]})
        elif e.get("kind") == "table_publisher":
            out.append({"via": "scope", "label": "table_publisher (rows pushed from Python)", "variables": [e["name"]]})
        elif e.get("java_class", "").startswith("Barrage"):
            out.append({"via": "scope", "label": "remote subscription", "variables": [e["name"]]})
    return out


def _listeners(rep: dict, scope: dict) -> dict:
    graph_cb = [n for n in rep["graph"].get("nodes", []) if n["kind"] == "callback" and n.get("active")]
    counts = Counter(n["description"] for n in graph_cb)
    handles = [e for e in rep["exports"] if e.get("kind") == "listener_handle"]
    return {
        "in_graph": [{"id": n["id"], "description": n["description"], "watches": n["parents"],
                      "ms_per_interval": n.get("ms_per_interval"), "calls_per_interval": n.get("calls_per_interval")}
                     for n in graph_cb],
        "handles_in_scope": [{"name": h["name"], "started": h.get("started"), "description": h.get("description")}
                             for h in handles],
        "stacked": {d: c for d, c in counts.items() if c > 1},
        "unreferenced_estimate": max(0, len(graph_cb) - len(handles)),
    }


def _outputs(rep: dict) -> list:
    out = [{"label": n["label"], "id": n["id"], "description": n["description"]}
           for n in rep["graph"].get("nodes", []) if n["kind"] == "sink"]
    for n in rep["listeners"].get("in_graph", []):
        out.append({"label": "Python listener (may write anywhere: tables, files, sockets, queues)",
                    "id": n["id"], "description": n["description"]})
    for e in rep["exports"]:
        if e.get("kind") in ("ui_element", "figure"):
            out.append({"label": f"exposed to clients as {e['kind']}", "variables": [e["name"]]})
    return out


# ----------------------------------------------------------------------------
# runtime: engine clock, memory, threads, sockets, libraries
# ----------------------------------------------------------------------------

def _runtime() -> dict:
    import jpy
    rt: dict = {}
    ctx = jpy.get_type("io.deephaven.engine.context.ExecutionContext").getContext()
    ug = ctx.getUpdateGraph()
    rt["update_graph"] = {"name": str(ug.getName()), "step": int(ug.clock().currentStep()),
                          "class": ug.getClass().getSimpleName()}
    try:
        pug = jpy.cast(ug, jpy.get_type("io.deephaven.engine.updategraph.impl.PeriodicUpdateGraph"))
        rt["update_graph"]["target_cycle_ms"] = int(pug.getTargetCycleDurationMillis())
    except Exception:  # noqa: BLE001
        pass

    try:
        from deephaven.server import executors
        rt["server_executors"] = list(executors.executor_names())
    except Exception:  # noqa: BLE001
        rt["server_executors"] = None
    # Embedded pip server: the console scope is the host process's own __main__.
    rt["embedded_pip_server"] = "deephaven_server" in sys.modules
    rt["report_thread"] = threading.current_thread().name

    jrt = jpy.get_type("java.lang.Runtime").getRuntime()
    rt["jvm_heap_mb"] = {"max": jrt.maxMemory() // 2**20, "total": jrt.totalMemory() // 2**20,
                         "used": (jrt.totalMemory() - jrt.freeMemory()) // 2**20}
    rt["process_rss_mb"] = _proc_status_mb("VmRSS")  # JVM + Python + native, whole process

    # Java threads that have called into Python show up in threading.enumerate()
    # as "java-..." dummy threads; keep them out of the list of Python-started threads.
    py_threads = threading.enumerate()
    rt["python_threads"] = [{"name": t.name, "daemon": t.daemon, "alive": t.is_alive(),
                             "target": _target_name(t)} for t in py_threads if not t.name.startswith("java-")]
    rt["java_threads_seen_by_python"] = sum(1 for t in py_threads if t.name.startswith("java-"))
    jthreads = jpy.get_type("java.lang.Thread").getAllStackTraces().keySet().toArray()
    groups = Counter(re.sub(r"[-_ ]?\d+$", "", str(t.getName())) for t in jthreads)
    rt["java_threads"] = {"count": len(jthreads), "by_name": dict(groups.most_common())}

    rt["listening_ports"] = _listening_ports()
    std = set(getattr(sys, "stdlib_module_names", ()))
    platform = {"deephaven", "deephaven_internal", "deephaven_core", "jpy", "jpyutil", "numpy", "pandas", "pyarrow",
                "numba", "dateutil", "pytz", "tzdata", "six", "_distutils_hack", "pkg_resources", "setuptools",
                "importlib_metadata", "zipp", "typing_extensions", "packaging", "jedi", "parso", "plotly",
                "deephaven_plugin_ui", "matplotlib", "PIL", "kiwisolver", "cycler", "fontTools", "pyparsing",
                "contourpy", "tenacity", "narwhals", "docstring_parser", "json_rpc", "jsonrpc", "attr", "attrs"}
    top = {m.split(".")[0] for m in list(sys.modules)}
    rt["third_party_modules"] = sorted(m for m in top if m not in std and m not in platform and not m.startswith("_"))
    try:
        from deephaven import perfmon
        from deephaven.pandas import to_pandas
        last = to_pandas(perfmon.server_state_log().tail(1))
        if len(last):
            rt["server_state_last_interval"] = {k: _jsonable(v) for k, v in last.iloc[0].to_dict().items()}
    except Exception as e:  # noqa: BLE001
        rt["server_state_last_interval"] = {"error": repr(e)}
    return rt


def _listening_ports():
    """Listening TCP ports in this process's network namespace (Linux only; None elsewhere)."""
    import os
    if not os.path.exists("/proc/self/net/tcp"):
        return None
    ports = set()
    for path in ("/proc/self/net/tcp", "/proc/self/net/tcp6"):
        try:
            with open(path) as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) > 3 and parts[3] == "0A":  # LISTEN
                        ports.add(int(parts[1].rsplit(":", 1)[1], 16))
        except OSError:
            pass
    return sorted(ports)


def _proc_status_mb(key: str):
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(key + ":"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None


def _target_name(t: threading.Thread):
    tgt = getattr(t, "_target", None)
    return getattr(tgt, "__qualname__", None) or (repr(tgt)[:60] if tgt else None)


# ----------------------------------------------------------------------------
# findings: things worth a human look
# ----------------------------------------------------------------------------

def _findings(rep: dict) -> list:
    f = []
    g, lis, rt = rep.get("graph", {}), rep.get("listeners", {}), rep.get("runtime", {})
    nodes = [n for n in g.get("nodes", []) if n.get("active")]

    if g and not g.get("ancestry_complete", True):
        f.append(("warn", "Graph ancestry is incomplete: open perfmon.update_performance_ancestors_log() "
                          "at worker start so dependencies are recorded."))
    for d, c in lis.get("stacked", {}).items():
        f.append(("warn", f"{c} active listeners share the description '{d}': likely stacked by re-run setup code."))
    if lis.get("unreferenced_estimate"):
        f.append(("info", f"{lis['unreferenced_estimate']} active listener(s) have no handle in scope; "
                          "they cannot be stopped without one (or they belong to another component)."))

    total = sum(n.get("ms_per_interval") or 0 for n in nodes)
    py = sum(n.get("ms_per_interval") or 0 for n in nodes if n["kind"] == "callback")
    if total and py / total > 0.25:
        f.append(("info", f"Python callbacks use {py / total:.0%} of engine time "
                          f"({py:.0f} of {total:.0f} ms per interval)."))
    orphans = [n for n in nodes if not n["reachable_from_scope"] and n["kind"] not in ("internal",)]
    if orphans:
        f.append(("info", f"{len(orphans)} active node(s) are not upstream of any scope variable or listener: "
                          "created by client sessions (grid sorts/filters, viewports, deephaven.ui renders) or leaked."))
    extra_threads = [t for t in rt.get("python_threads", []) if t["name"] != "MainThread"]
    if extra_threads:
        f.append(("info", f"{len(extra_threads)} Python thread(s) besides MainThread: "
                          + ", ".join(t["name"] for t in extra_threads[:6]) + " (non-engine work running in the worker)."))
    side = [p for p in (rt.get("listening_ports") or []) if p not in (10000, 8080, 8443, 9000)]
    if side:
        f.append(("warn", f"Listening ports besides the server's: {side} (side servers inside the worker)."))
    if rt.get("third_party_modules"):
        f.append(("info", "Non-platform libraries loaded: " + ", ".join(rt["third_party_modules"][:12])))
    graphs = g.get("update_graphs") or []
    if len(graphs) > 1:
        f.append(("info", f"{len(graphs)} update graphs have engine nodes: {graphs}. Tables on a non-default "
                          "graph advance on that graph's own clock (event-driven graphs only on requestRefresh())."))
    if rt.get("embedded_pip_server"):
        f.append(("warn", "Embedded pip server: the console scope is the host process's own __main__, so any client "
                          "with console access can read and modify the host's module globals."))
    published_private = [e["name"] for e in rep.get("exports", []) if e.get("underscore")
                         and e.get("kind") in ("table", "input_table", "static_table", "partitioned_table",
                                               "hierarchical_table", "figure", "ui_element")]
    if published_private:
        f.append(("info", f"Underscore-named objects published as fields anyway: {published_private[:8]}"))
    unstarted = [h["name"] for h in lis.get("handles_in_scope", []) if h.get("started") is False]
    if unstarted:
        f.append(("info", f"Listener handles in scope that are stopped: {unstarted}"))
    return [{"level": lvl, "message": msg} for lvl, msg in f]


# ----------------------------------------------------------------------------
# publishing + rendering
# ----------------------------------------------------------------------------

def _publish(rep: dict, scope: dict) -> None:
    from deephaven import new_table
    from deephaven.column import bool_col, double_col, long_col, string_col

    ex = rep["exports"]
    scope["dhi_exports"] = new_table([
        string_col("Name", [e["name"] for e in ex]),
        string_col("Kind", [e.get("kind", "") for e in ex]),
        string_col("Detail", [_export_detail(e) for e in ex]),
    ])
    nodes = rep["graph"].get("nodes", [])
    if nodes:
        scope["dhi_nodes"] = new_table([
            long_col("Id", [n["id"] for n in nodes]),
            string_col("Kind", [n["kind"] for n in nodes]),
            string_col("Label", [n["label"] for n in nodes]),
            string_col("Variables", [", ".join(n["variables"]) for n in nodes]),
            double_col("MsPerInterval", [float(n.get("ms_per_interval") or 0) for n in nodes]),
            bool_col("Active", [bool(n.get("active")) for n in nodes]),
            bool_col("ReachableFromScope", [n["reachable_from_scope"] for n in nodes]),
            string_col("Description", [n["description"] for n in nodes]),
        ])
    fs = rep["findings"]
    scope["dhi_findings"] = new_table([string_col("Level", [x["level"] for x in fs]),
                                       string_col("Message", [x["message"] for x in fs])])
    scope["dhi_report"] = new_table([string_col("Json", [json.dumps(rep, default=_jsonable)])])


def _export_detail(e: dict) -> str:
    k = e.get("kind")
    if k in ("table", "input_table", "static_table"):
        flags = [x for x, on in (("refreshing", e.get("refreshing")), ("blink", e.get("blink"))) if on]
        return f"{e.get('rows')} rows x {e.get('columns')} cols, {e.get('java_class')} {' '.join(flags)}".strip()
    if k == "callable":
        return f"{e['name']}{e.get('signature') or ''}"
    if k == "ui_element":
        return f"{e.get('ui_type')} {e.get('component') or ''}".strip()
    if k == "listener_handle":
        return f"started={e.get('started')} {e.get('description') or ''}".strip()
    return e.get("py_type", "")


def render_text(rep: dict, max_rows: int = 40) -> str:
    """Human-readable report. Works on the dict, or on JSON fetched by a client."""
    if isinstance(rep, str):
        rep = json.loads(rep)
    L = []
    add = L.append
    add(f"Deephaven application report  ({rep.get('generated_at')}, {rep.get('elapsed_ms')} ms)")
    fields = rep.get("server_fields")
    if fields:
        add(f"\nEXPORTED FIELDS (server registry, what any client can open): {len(fields)}")
        for fld in fields[:max_rows]:
            app = fld["application_id"] if fld["application_id"] != "scope" else "console scope"
            add(f"  {fld['field_name']:<28} {fld['type']:<36} [{app}]")

    by_kind = defaultdict(list)
    for e in rep.get("exports", []):
        by_kind[e.get("kind", "?")].append(e)
    add(f"\nSCOPE OBJECTS: {sum(len(v) for v in by_kind.values())}")
    for kind in sorted(by_kind):
        add(f"  {kind} ({len(by_kind[kind])})")
        for e in by_kind[kind][:max_rows]:
            add(f"    {e['name']:<26} {_export_detail(e)}")

    g = rep.get("graph", {})
    nodes = g.get("nodes", [])
    act = [n for n in nodes if n.get("active")]
    add(f"\nUPDATE GRAPH: {len(act)} active nodes, {len(g.get('edges', []))} edges, "
        f"ancestry {'complete' if g.get('ancestry_complete') else 'INCOMPLETE'}; "
        f"graphs: {', '.join(g.get('update_graphs') or ['?'])}")
    hot = sorted(act, key=lambda n: -(n.get("ms_per_interval") or 0))[:10]
    if hot:
        add("  costliest (ms per interval):")
        for n in hot:
            name = ", ".join(n["variables"]) or "-"
            add(f"    {n.get('ms_per_interval', 0):>8.1f}  {n['kind']:<9} {n['label']:<28} {name}")

    add("\nINPUTS (what the app is subscribed to / fed by):")
    for i in rep.get("inputs", [])[:max_rows]:
        add(f"  {i['label']:<44} {', '.join(i.get('variables') or []) or i.get('description', '')[:60]}")

    lis = rep.get("listeners", {})
    add(f"\nLISTENERS: {len(lis.get('in_graph', []))} active in graph, {len(lis.get('handles_in_scope', []))} handles in scope")
    for n in lis.get("in_graph", [])[:max_rows]:
        add(f"  {n['description']:<30} watches {n['watches']}  {n.get('ms_per_interval')} ms/interval")

    add("\nOUTPUTS (sinks and exposure):")
    for o in rep.get("outputs", [])[:max_rows]:
        add(f"  {o['label']:<60} {', '.join(o.get('variables') or []) or o.get('description', '')[:40]}")

    rt = rep.get("runtime", {})
    ugd = rt.get("update_graph", {})
    add(f"\nRUNTIME: update graph {ugd.get('name')} step {ugd.get('step')}"
        f"{', target cycle ' + str(ugd.get('target_cycle_ms')) + ' ms' if ugd.get('target_cycle_ms') else ''}")
    heap = rt.get("jvm_heap_mb", {})
    add(f"  JVM heap used/total/max MB: {heap.get('used')}/{heap.get('total')}/{heap.get('max')};"
        f" process RSS MB: {rt.get('process_rss_mb') or 'unavailable on this OS'}")
    add(f"  Python threads: " + ", ".join(f"{t['name']}{'' if t['daemon'] else '(non-daemon)'}"
                                          for t in rt.get("python_threads", [])))
    ports = rt.get("listening_ports")
    add(f"  Java threads: {rt.get('java_threads', {}).get('count')}; listening ports: "
        f"{ports if ports is not None else 'unavailable on this OS'}")
    add(f"  server executors: {rt.get('server_executors')}; embedded pip server: {rt.get('embedded_pip_server')}; "
        f"report ran on thread: {rt.get('report_thread')}")
    if rt.get("third_party_modules"):
        add(f"  non-platform libraries: {', '.join(rt['third_party_modules'])}")

    add("\nFINDINGS:")
    for x in rep.get("findings", []) or [{"level": "ok", "message": "nothing notable"}]:
        add(f"  [{x['level']}] {x['message']}")
    for e in rep.get("errors", []):
        add(f"  [error] section {e['section']}: {e['error']}")
    return "\n".join(L)


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _default_scope(scope):
    if scope is not None:
        return scope
    import __main__
    return vars(__main__)


def _guard(rep, section, fn, default):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - report partial results, never fail the whole call
        rep["errors"].append({"section": section, "error": repr(e)[:300]})
        return default


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _jsonable(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)
