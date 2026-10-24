"""
When is moving a node from Python to Java worth it? Two kinds of slow node, measured:

  1. A per-row function in a formula, on 2,000,000 rows:
       Python UDF   update("S = py_score(Px, MA, VWAP)")
       Java static  update("S = com.acme.hybrid.Fast.score(Px, MA, VWAP)")
       inline       update("S = <the same math in the formula language>")
  2. A stateful listener (rung 3's flip tracker) on a ticking table, stepped on our own clock
       (20,000 symbols, 20,000 signal updates per step, 100 steps, same seeded data, best of 3):
       no listener (graph cost only) | Python SignalTracker | Java SignalFlipTracker

Run with the server venv (builds the jar first):
    .venv-server/Scripts/python hybrid/src/test/python/bench.py
Results: hybrid/results/bench.json
"""
import json
import math
import os
import pathlib
import random
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve().parents[3]   # hybrid/
sys.path.insert(0, str(HERE))
OUT = HERE / "results" / "bench.json"
R = {}


def jvm_args() -> list:
    args = ["-Xmx3g", "-DAuthHandlers=io.deephaven.auth.AnonymousAuthenticationHandler"]
    if os.name == "nt":
        jh = pathlib.Path(os.environ["JAVA_HOME"])
        for d in (jh / "bin", jh / "bin" / "server"):
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"
            os.add_dll_directory(str(d))
        args += ["-Dweb.storage.layout.directory=layouts", "-Dweb.storage.notebook.directory=notebooks"]
    return args


def timed(fn, repeat=3):
    ts = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return round(statistics.median(ts), 3)


def py_score(px: float, ma: float, vwap: float) -> float:  # the same math as Fast.score
    if math.isnan(px) or math.isnan(ma) or math.isnan(vwap) or vwap == 0:
        return math.nan
    return math.tanh(50 * (ma - vwap) / vwap) - 0.5 * math.tanh(20 * (px - ma) / ma)


def main() -> None:
    from build import build
    jar = build()
    from deephaven_server import Server
    Server(port=int(os.environ.get("DH_PORT", "10014")), jvm_args=jvm_args(), extra_classpath=[str(jar)]).start()

    import __main__
    __main__.py_score = py_score
    from deephaven import empty_table

    # ---------------------------------------------------------------- 1. row functions
    n = 2_000_000
    base = empty_table(n).update(["Px = 100 + (ii % 1000) / 100.0", "MA = 100 + (ii % 997) / 100.0",
                                  "VWAP = 100 + (ii % 991) / 100.0"]).select()
    inline = "S = (VWAP == 0) ? NULL_DOUBLE : Math.tanh(50 * (MA - VWAP) / VWAP) - 0.5 * Math.tanh(20 * (Px - MA) / MA)"
    row = {"rows": n,
           "python_udf_s": timed(lambda: base.update("S = py_score(Px, MA, VWAP)").select(), repeat=1),
           "java_static_s": timed(lambda: base.update("S = com.acme.hybrid.Fast.score(Px, MA, VWAP)").select()),
           "inline_formula_s": timed(lambda: base.update(inline).select())}
    from deephaven.pandas import to_pandas
    a = to_pandas(base.head(1000).update("S = py_score(Px, MA, VWAP)"))["S"]
    b = to_pandas(base.head(1000).update("S = com.acme.hybrid.Fast.score(Px, MA, VWAP)"))["S"]
    row["same_values"] = bool(((a - b).abs() < 1e-12).all())
    row["java_speedup_vs_python"] = round(row["python_udf_s"] / row["java_static_s"], 1)
    # A null cell reaches Java as the NULL_DOUBLE sentinel; Fast.score must return null, not a number.
    nulls = to_pandas(empty_table(3).update(["Px = i == 1 ? NULL_DOUBLE : 101.0", "MA = 100.5", "VWAP = 100.0",
                                             "S = com.acme.hybrid.Fast.score(Px, MA, VWAP)"]))["S"]
    row["java_null_in_null_out"] = bool(nulls.isna().tolist() == [False, True, False])
    R["1_row_function"] = row
    print("1", row, flush=True)

    # ---------------------------------------------------------------- 2. stateful listener
    run_listener("none", steps=20)  # JIT warm-up for the graph itself, discarded
    def best(kind):  # best of 3 fresh runs (each on its own clock and tables)
        runs = [run_listener(kind, n_syms=20_000, rows_per_step=20_000, steps=100, seed=11) for _ in range(3)]
        return min(runs, key=lambda r: r["seconds"])
    R["2_stateful_listener"] = {k: best(k) for k in ("none", "java", "python")}
    l2 = R["2_stateful_listener"]
    l2["python_listener_cost_s"] = round(l2["python"]["seconds"] - l2["none"]["seconds"], 3)
    l2["java_listener_cost_s"] = round(l2["java"]["seconds"] - l2["none"]["seconds"], 3)
    l2["same_flips"] = l2["python"]["flips"] == l2["java"]["flips"]
    if l2["java_listener_cost_s"] > 0:
        l2["java_speedup_vs_python"] = round(l2["python_listener_cost_s"] / l2["java_listener_cost_s"], 1)
    print("2", {k: v for k, v in l2.items() if not isinstance(v, dict)}, flush=True)

    OUT.write_text(json.dumps(R, indent=2), encoding="utf-8")
    print("wrote", OUT)
    os._exit(0)


_RUNS = [0]


def run_listener(kind: str, n_syms=2000, rows_per_step=2000, steps=100, seed=11):
    import jpy
    from deephaven import dtypes as dht
    from deephaven import new_table
    from deephaven.column import string_col
    from deephaven.execution_context import ExecutionContext, get_exec_ctx
    from deephaven.stream import blink_to_append_only
    from deephaven.stream.table_publisher import table_publisher
    from deephaven.table_listener import listen
    from deephaven.update_graph import UpdateGraph

    ug = jpy.get_type("io.deephaven.engine.updategraph.impl.EventDrivenUpdateGraph").newBuilder(f"bench-{kind}-{_RUNS[0]}").build()
    _RUNS[0] += 1
    ctx = ExecutionContext(j_exec_ctx=get_exec_ctx().j_exec_ctx.withUpdateGraph(ug))
    rnd = random.Random(seed)
    syms = [f"S{i:04d}" for i in range(n_syms)]
    batches = [new_table([string_col("Sym", [rnd.choice(syms) for _ in range(rows_per_step)]),
                          string_col("Signal", [rnd.choice(("LONG", "SHORT")) for _ in range(rows_per_step)])])
               for _ in range(steps)]
    with ctx:
        feed, pub = table_publisher(f"feed-{kind}-{_RUNS[0]}", {"Sym": dht.string, "Signal": dht.string},
                                    update_graph=UpdateGraph(j_update_graph=ug))
        signals = blink_to_append_only(feed).last_by("Sym")
        tracker = None
        if kind == "python":
            tracker = PySignalTracker(ug)
            handle = listen(signals, tracker.on_data)
        elif kind == "java":
            tracker = jpy.get_type("com.acme.hybrid.SignalFlipTracker").attach(signals.j_table)
        t0 = time.perf_counter()
        for b in batches:
            pub.add(b)
            ug.requestRefresh()
        secs = time.perf_counter() - t0
        flips = tracker.flips if kind == "python" else (tracker.flipCount() if kind == "java" else 0)
        if kind == "python":
            handle.stop()
    return {"steps": steps, "rows_per_step": rows_per_step, "symbols": n_syms, "seconds": round(secs, 3),
            "ms_per_step": round(1000 * secs / steps, 2), "flips": int(flips)}


class PySignalTracker:
    """Rung 3's SignalTracker logic (positions, flip detection, flips published to a table)."""

    def __init__(self, ug):
        from deephaven import dtypes as dht
        from deephaven.stream.table_publisher import table_publisher
        from deephaven.update_graph import UpdateGraph
        self.position, self.flips, self.ug = {}, 0, ug
        _, self.pub = table_publisher("py_flips", {"Step": dht.int64, "Sym": dht.string, "From": dht.string,
                                                   "To": dht.string}, update_graph=UpdateGraph(j_update_graph=ug))

    def on_data(self, update, is_replay):
        from deephaven import new_table
        from deephaven.column import long_col, string_col
        for sym, sig in zip(update.added().get("Sym", []), update.added().get("Signal", [])):
            self.position[sym] = 1 if sig == "LONG" else -1
        if "Signal" not in (update.modified_columns or []):
            return
        now, prev = update.modified(), update.modified_prev()
        rows = []
        for sym, p, c in zip(now["Sym"], prev["Signal"], now["Signal"]):
            if p != c:
                self.flips += 1
                self.position[sym] = 1 if c == "LONG" else -1
                rows.append((sym, p, c))
        if rows:
            step = self.ug.clock().currentStep()
            self.pub.add(new_table([long_col("Step", [step] * len(rows)), string_col("Sym", [r[0] for r in rows]),
                                    string_col("From", [r[1] for r in rows]), string_col("To", [r[2] for r in rows])]))


if __name__ == "__main__":
    main()
