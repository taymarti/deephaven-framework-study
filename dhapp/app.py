"""
dhapp.App: a Deephaven application as four kinds of parts, wired by name.

    app = App("mm_book", catalog)

    app.source("quotes", schemas.QUOTES, history=load_quotes)    # pushed live, replayed in backtest
    app.source("limits", catalog="desk_limits")                   # wherever the catalog says it lives

    @app.stage                                                    # a pure function: tables in, tables out
    def book(quotes, limits): ...                                 # parameter names ARE table names

    @app.action(on="orders", services=["broker"])                 # the only per-cycle Python
    def route(rows, broker): broker.send(rows)

    app.service("broker", live=RealBroker(), sim=RecordingBroker())
    app.surface("book", "risk")                                   # published names (and the dashboard)
    app.start("live")      # or "backtest" / "test"

Modes
  live      default ~1 s clock; push-fed sources are table_publishers (app.feed) or a `live=` factory
  backtest  an event-driven graph; app.run_history() replays every history= source in time buckets,
            one checkpoint per bucket, as fast as the engine computes; services use `sim`
  test      same clock as backtest; you call app.feed(...) and app.step() and assert on app.table(...)

Catalog and live-factory sources tick on the default clock, so in backtest/test they are frozen
with .snapshot() (an engine rule: one graph cannot mix two refreshing clocks).
"""
import inspect
import threading
import time
import traceback
from typing import Callable, Optional, Sequence

LIVE, BACKTEST, TEST = "live", "backtest", "test"


class App:
    def __init__(self, name: str, catalog=None):
        from dhapp.catalog import Catalog
        self.name = name
        self.catalog = catalog or Catalog()
        self.mode: Optional[str] = None
        self.tables: dict = {}
        self._sources: dict = {}
        self._stages: list = []
        self._actions: list = []
        self._services: dict = {}
        self._surfaces: list = []
        self._pubs: dict = {}
        self._handles: list = []
        self._health = {}
        self._health_lock = threading.Lock()
        self._ug = self._ctx = None

    # ------------------------------------------------------------ declare
    def source(self, name: str, schema: Optional[dict] = None, *, live: Optional[Callable] = None,
               history: Optional[Callable] = None, catalog: Optional[str] = None, append_only: bool = True):
        """A source is one of: pushed (schema; rows via app.feed), live=factory, catalog=logical name.
        history= gives a static table replayed in backtest mode."""
        self._sources[name] = dict(schema=schema, live=live, history=history, catalog=catalog, append_only=append_only)
        return self

    def stage(self, fn: Callable = None, *, outputs: Optional[Sequence[str]] = None):
        """Decorator. Parameters are input table names; return a table (named after the function)
        or a dict of name -> table."""
        def register(f):
            self._stages.append((f, list(inspect.signature(f).parameters), outputs))
            return f
        return register(fn) if fn else register

    def action(self, on: str, services: Sequence[str] = (), name: Optional[str] = None):
        """Decorator. fn(rows: pandas.DataFrame of rows ADDED to `on` this cycle, **services).
        Exceptions are caught and recorded in app.health; the action keeps running."""
        def register(f):
            self._actions.append((name or f.__name__, f, on, list(services)))
            return f
        return register

    def service(self, name: str, *, live, sim):
        self._services[name] = {"live": live, "sim": sim}
        return self

    def surface(self, *names: str):
        self._surfaces += [n for n in names if n not in self._surfaces]
        return self

    # ------------------------------------------------------------ run
    def start(self, mode: str = LIVE):
        if self.mode:
            raise RuntimeError(f"{self.name} already started in {self.mode} mode")
        self.mode = mode
        if mode == LIVE:
            self._build()
        else:
            import jpy
            from deephaven.execution_context import ExecutionContext, get_exec_ctx
            edug = jpy.get_type("io.deephaven.engine.updategraph.impl.EventDrivenUpdateGraph")
            self._ug = edug.newBuilder(f"{self.name}-{mode}-{id(self)}").build()
            self._ctx = ExecutionContext(j_exec_ctx=get_exec_ctx().j_exec_ctx.withUpdateGraph(self._ug))
            with self._ctx:
                self._build()
            self.step()  # apply initial rows (input tables, static joins)
        return self

    def feed(self, source: str, table) -> None:
        """Push rows into a pushed source (any thread). Visible at the next cycle / app.step()."""
        self._pubs[source].add(table)

    def step(self) -> None:
        """backtest/test: one checkpoint now; returns when it has finished."""
        if self._ug is None:
            raise RuntimeError("step() is for backtest/test mode; live mode runs on the default clock")
        self._ug.requestRefresh()

    def run_history(self, bucket_ms: int = 1000, ts: str = "Timestamp") -> dict:
        """backtest: replay every history= source in time order, one checkpoint per bucket."""
        import pandas as pd
        from deephaven.pandas import to_pandas, to_table
        frames = []
        for name, s in self._sources.items():
            if s["history"] is not None:
                df = to_pandas(s["history"]())
                df["__src"], df["__bucket"] = name, df[ts].astype("int64") // (bucket_ms * 1_000_000)
                frames.append(df)
        if not frames:
            return {"buckets": 0}
        allrows = pd.concat(frames).sort_values([ts], kind="stable")
        t0 = time.perf_counter()
        n = 0
        for _, group in allrows.groupby("__bucket", sort=True):
            for src, rows in group.groupby("__src", sort=False):
                with self._ctx:
                    self.feed(src, to_table(rows.drop(columns=["__src", "__bucket"]).reset_index(drop=True)))
            self.step()
            n += 1
        return {"buckets": n, "rows": len(allrows), "seconds": round(time.perf_counter() - t0, 3)}

    def table(self, name: str):
        return self.tables[name]

    def stop(self) -> None:
        for h in self._handles:
            h.stop()
        self._handles.clear()

    @property
    def health(self):
        """A live table: one row per action (Calls, Errors, LastError)."""
        return self.tables["health"]

    # ------------------------------------------------------------ internals
    def _build(self) -> None:
        from deephaven.stream import blink_to_append_only
        from deephaven.stream.table_publisher import table_publisher
        from dhapp.schemas import validate
        ug_kw = {}
        if self._ug is not None:
            from deephaven.update_graph import UpdateGraph
            ug_kw = {"update_graph": UpdateGraph(j_update_graph=self._ug)}
        sim = self.mode != LIVE

        for name, s in self._sources.items():
            if s["catalog"]:
                t = self.catalog.resolve(s["catalog"])
                t = t.snapshot() if sim and t.is_refreshing else t
            elif s["live"] is not None and not sim:
                t = s["live"]()
            else:
                blink, pub = table_publisher(f"{self.name}.{name}", s["schema"], **ug_kw)
                self._pubs[name] = pub
                t = blink_to_append_only(blink) if s["append_only"] else blink
            if s["schema"]:
                validate(t, s["schema"], name)
            self.tables[name] = t

        pending = list(self._stages)
        while pending:  # run each stage once all its inputs exist (registration order otherwise)
            ready = [st for st in pending if all(p in self.tables for p in st[1])]
            if not ready:
                missing = {p for _, ps, _ in pending for p in ps if p not in self.tables}
                raise KeyError(f"{self.name}: no source or stage produces {sorted(missing)}")
            for st in ready:
                fn, params, outputs = st
                out = fn(**{p: self.tables[p] for p in params})
                self.tables.update(out if isinstance(out, dict) else {fn.__name__: out})
                pending.remove(st)

        hblink, self._health_pub = table_publisher(f"{self.name}.health",
                                                   {"Action": _dt().string, "Calls": _dt().int64,
                                                    "Errors": _dt().int64, "LastError": _dt().string}, **ug_kw)
        self.tables["health"] = blink_to_append_only(hblink).last_by("Action")
        for name, fn, on, services in self._actions:
            self._attach(name, fn, on, {s: self._services[s]["sim" if sim else "live"] for s in services})

        import __main__
        for n in self._surfaces + ["health"]:  # published as fields every client and UI can open
            setattr(__main__, f"{self.name}_{n}", self.tables[n])

    def _attach(self, name, fn, on, services) -> None:
        import pandas as pd
        from deephaven.table_listener import listen
        self._health[name] = {"Calls": 0, "Errors": 0, "LastError": ""}
        self._report(name)

        def on_update(update, is_replay):
            added = update.added()
            if not added or not len(next(iter(added.values()))):
                return
            h = self._health[name]
            h["Calls"] += 1
            try:
                fn(pd.DataFrame({k: list(v) for k, v in added.items()}), **services)
            except Exception as e:  # noqa: BLE001 - a raised exception would stop the listener for good
                h["Errors"] += 1
                h["LastError"] = f"{type(e).__name__}: {e}"[:300]
                traceback.print_exc()
            self._report(name)

        self._handles.append(listen(self.tables[on], on_update, description=f"{self.name}.{name}"))

    def _report(self, name) -> None:
        from deephaven import new_table
        from deephaven.column import long_col, string_col
        h = self._health[name]
        self._health_pub.add(new_table([string_col("Action", [name]), long_col("Calls", [h["Calls"]]),
                                        long_col("Errors", [h["Errors"]]), string_col("LastError", [h["LastError"]])]))


def _dt():
    from deephaven import dtypes
    return dtypes
