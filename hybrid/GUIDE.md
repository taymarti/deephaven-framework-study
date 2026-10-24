# Java in Deephaven apps: a practical guide

This guide teaches how to combine Java and Python in one Deephaven application,
in either direction: Java subordinate to a Python project, or Python subordinate
to a Java one. Every pattern below is working code in this folder, tested on
Deephaven Community 42.6 (pip server, native Windows, Java 17). Where something
was not tested here, it says so.

Contents:

1. [The mental model](#1-the-mental-model)
2. [What crosses the boundary, and what it costs](#2-what-crosses-the-boundary-and-what-it-costs)
3. [Architecture A: Python primary, Java subordinate](#3-architecture-a-python-primary-java-subordinate)
4. [Architecture B: Java primary, Python subordinate](#4-architecture-b-java-primary-python-subordinate)
5. [Choosing between them](#5-choosing-between-them)
6. [The boundary, rule by rule](#6-the-boundary-rule-by-rule)
7. [Project layout and build (Maven)](#7-project-layout-and-build-maven)
8. [Running locally and on Enterprise](#8-running-locally-and-on-enterprise)
9. [Testing](#9-testing)
10. [Measured performance, and what to move](#10-measured-performance-and-what-to-move)
11. [Limits we hit](#11-limits-we-hit)

---

## 1. The mental model

A Deephaven worker is **one process**: a JVM running the engine, with a CPython
interpreter embedded in it. The two halves are joined by **jpy**, a bridge that
lets Python call Java objects directly and lets the engine call back into Python.

```text
 ┌──────────────────────────── one worker process ────────────────────────────┐
 │  JVM: the Deephaven engine                                                 │
 │    update graph, tables, column sources, listeners, publishers, server     │
 │         ▲   Java classes from YOUR jar run here too, as native engine code │
 │         │                                                                  │
 │       jpy (in-process bridge: no network, no serialization of tables)      │
 │         │                                                                  │
 │  CPython (embedded): the `deephaven` package is a thin wrapper over the    │
 │    engine's Java objects; your Python code runs here, under the GIL       │
 └────────────────────────────────────────────────────────────────────────────┘
```

Three consequences follow:

- **Everything is already Java.** A Python `Table` is a wrapper around a Java
  `Table` (`t.j_table`). Tables, the update graph and listeners all live in the
  engine. Adding Java means writing code in the engine's own language, beside it.
- **Java and Python share objects, not copies.** A table built in Java can be
  used from Python, and vice versa, at no cost. Only *row values* cost anything,
  when they cross into Python.
- **The engine is not Python-bound.** Anything you move from Python to Java stops
  holding the GIL, so it also stops slowing every other Python thread in the
  process.

## 2. What crosses the boundary, and what it costs

| You write | What happens per update | Cost driver |
|---|---|---|
| Built-in table operations (`update_by`, `agg_by`, joins, `where`) | Engine Java, incremental | None extra |
| A formula: `update("S = X * 2")` | Compiled to Java bytecode, per row | None extra |
| A Java static method in a formula | Called per row from compiled code, JIT-inlined | Your method's work |
| A Python function in a formula | Each row crosses into Python, under the GIL | Crossing plus Python per row |
| A Java listener | Reads column sources directly on the update thread | Your loop's work |
| A Python listener | Changed rows converted to numpy arrays, then Python runs, under the GIL | Conversion plus Python per row |

The rule of thumb is that **per-row Python is the expensive thing**, in formulas
and in listeners alike. Per-cycle Python that touches few rows is cheap.

## 3. Architecture A: Python primary, Java subordinate

This is the common case: your team writes Deephaven in Python, and a few nodes
are too slow. You keep the graph in Python and drop in Java for the hot nodes.
See `src/main/python/hybrid_py.py`.

```text
 Python declares the graph ──► Java supplies hot nodes
   sources, joins, aggs          Fast.score(...)        per-row function
   update_by, UI, actions        SignalFlipTracker      stateful listener + output table
```

### 3a. A per-row function in Java

Write a `public static` method with primitive arguments:

```java
// src/main/java/com/acme/hybrid/Fast.java
public static double score(double px, double ma, double vwap) {
    if (px == NULL_DOUBLE || ma == NULL_DOUBLE || vwap == NULL_DOUBLE) return NULL_DOUBLE;   // see section 6
    return Math.tanh(50 * (ma - vwap) / vwap) - 0.5 * Math.tanh(20 * (px - ma) / ma);
}
```

Call it from a Python formula by its fully qualified name:

```python
signals = signals.update("Score = com.acme.hybrid.Fast.score(Px, MA50, VWAP)")
```

### 3b. A stateful node in Java

This is a listener that keeps state and emits rows. It is the Java form of the
"listener plus `table_publisher`" pattern. Extend
`InstrumentedTableUpdateListenerAdapter`, read values from column sources, and
write results through a Java `TablePublisher`:

```java
// src/main/java/com/acme/hybrid/SignalFlipTracker.java (abridged)
public final class SignalFlipTracker extends InstrumentedTableUpdateListenerAdapter {
    private final ColumnSource<String> sym, signal;
    private final TablePublisher publisher = TablePublisher.of("java_flips", FLIPS, t -> {}, () -> {});

    public static SignalFlipTracker attach(Table signals) {
        SignalFlipTracker t = new SignalFlipTracker(signals);   // also reads existing rows (section 6)
        signals.addUpdateListener(t);
        return t;
    }

    @Override public void onUpdate(TableUpdate up) {
        // modified() pairs with getModifiedPreShift(): current vs previous value of each changed row
        try (RowSet.Iterator now = up.modified().iterator(); RowSet.Iterator pre = up.getModifiedPreShift().iterator()) {
            while (now.hasNext()) {
                long k = now.nextLong(), kp = pre.nextLong();
                String cur = signal.get(k), prev = signal.getPrev(kp);
                if (cur != null && !cur.equals(prev)) { /* collect a flip row */ }
            }
        }
        publisher.add(/* TableTools.newTable(FLIPS, ...) of the collected rows */);
    }

    public Table flips() { return publisher.table(); }   // a blink table
}
```

Attach it from Python with jpy, and wrap its output as a Python `Table`:

```python
import jpy
from deephaven.table import Table
from deephaven.stream import blink_to_append_only

SignalFlipTracker = jpy.get_type("com.acme.hybrid.SignalFlipTracker")
_tracker = SignalFlipTracker.attach(signals.j_table)      # keep the reference!
flips = blink_to_append_only(Table(j_table=_tracker.flips()))
```

### 3c. A whole sub-graph in Java

A Java method can take tables and return tables, a "Java recipe". Python calls
it like any other function, with `Table(j_table=JavaRecipe.build(t.j_table))`.
This is how to move a dense cluster of operations whose logic is easier to write
in Java. Built-in operations inside it are just as incremental as from Python.

## 4. Architecture B: Java primary, Python subordinate

Choose this when the core is Java: an existing Java library, a Java team, or
logic that must not depend on Python. Java builds the graph; Python adds the
parts Python is good at. See `src/main/java/com/acme/hybrid/HybridApp.java` and
`src/main/resources/app.d/java/hybrid_java.py`.

```text
 Java builds the graph ──► Python adds the edges
   HybridApp.start():             publish the tables (scope)
   time_table, updateBy,          actions on Java tables: alerts, order routing, HTTP
   aggBy, naturalJoin,            ML models, deephaven.ui dashboards, orchestration
   SignalFlipTracker
```

The Java side builds the whole graph and returns what to publish:

```java
public static Map<String, Object> start() {
    Table trades  = TableTools.timeTable("PT0.1s").update("Sym = ...", "Px = ...", "Qty = ...");
    Table vwap    = trades.aggBy(List.of(Aggregation.AggWAvg("Qty", "VWAP = Px"), ...), "Sym");
    Table signals = trades.updateBy(UpdateByOperation.RollingAvg(50, "MA50 = Px"), "Sym")
                          .lastBy("Sym").naturalJoin(vwap, "Sym", "VWAP")
                          .update("Signal = MA50 > VWAP ? `LONG` : `SHORT`", "Score = com.acme.hybrid.Fast.score(Px, MA50, VWAP)");
    tracker = SignalFlipTracker.attach(signals);
    return Map.of("hy_trades", trades, "hy_signals", signals,
                  "hy_flips", BlinkTableTools.blinkToAppendOnly(tracker.flips()));
}
```

The Python loader publishes the tables, then adds Python's parts. Here that is
an alert action on the Java-built flips:

```python
_it = jpy.get_type("com.acme.hybrid.HybridApp").start().entrySet().iterator()
while _it.hasNext():
    _e = _it.next()
    globals()[_e.getKey()] = Table(j_table=_e.getValue())     # publish into the scope

_hy_alert_handle = listen(hy_flips, _on_flips, do_replay=True)  # a Python action on a Java table
```

**Why a Python loader and not `java -jar`?** The pip server runs only Python
application scripts and ships no standalone Java launcher (section 11). The jar
is therefore the *logic's* entry point, and a one-line script is the
*process's*. On a Groovy-console server (the Docker image or the standalone
`server-jetty-app` distribution), the loader can be the Groovy one-liner in
`src/main/resources/app.d/groovy-console/`.

**Tested:** the Java entry published `hy_trades`, `hy_signals`, `hy_flips` and
`hy_alerts` into the scope. The tables ticked, and the Python alert count
matched the Java flip count, one cycle behind; see section 6.

## 5. Choosing between them

| Situation | Choose |
|---|---|
| Team writes Python; a few nodes are slow | **A**: keep Python, move the hot nodes |
| Existing Java analytics or pricing library | **B**: the library builds or feeds the graph; Python adds UI and actions |
| Logic must be identical in a Java service and in Deephaven | **B** (or 3c): one Java implementation, called from both |
| Heavy ML or pandas work | **A**, with ML in Python; keep it out of per-row listeners |
| Order routing, alerts, HTTP calls | Python is fine in either; this work is I/O-bound, not CPU-bound |

Both directions use the same jar, and they can mix freely. A Python project can
call a Java recipe (3c) that itself attaches a Java listener.

## 6. The boundary, rule by rule

1. **Classes.** Use `jpy.get_type("com.acme.X")` from Python. In formulas, use
   the fully qualified name `com.acme.X.f(...)`. `query_library.import_static("com.acme.X")`
   failed for jars added with `extra_classpath`, because Class.forName cannot see
   them; `importStatic` with the Class object worked (ledger X1, X2).
2. **Tables.** A Python `Table` wraps a Java one: pass `t.j_table` to Java, and
   wrap a returned Java table with `Table(j_table=...)`.
3. **Nulls.** A null primitive cell reaches Java as a sentinel
   (`QueryConstants.NULL_DOUBLE`, `NULL_LONG`, and so on), not as NaN. Check for
   it and return the sentinel. A plain NaN check would compute nonsense on the
   huge negative sentinel. Tested: null in gives null out (`results/bench.json`).
4. **Keep references.** A listener or publisher that nothing references can be
   released. Hold the Java object in a Python global or a Java static field.
5. **Attach timing.** The graph is already ticking while an app script runs, so
   rows can exist before a listener attaches. In Python, use
   `listen(..., do_replay=True)`. In Java, read the current rows in the
   constructor, as `SignalFlipTracker` does. Without this, the first flip was
   missed.
6. **One cycle per hop.** Rows a listener publishes appear at the **next**
   cycle, Java or Python. A chain of listener and publisher pairs adds one cycle
   per hop.
7. **Previous values.** Pair `upstream.modified()` with
   `upstream.getModifiedPreShift()`, then read `getPrev(preKey)` for the old
   value and `get(key)` for the new one.
8. **Execution context.** Java code that builds tables uses the calling thread's
   context, so Python's `with ctx:` applies to the Java calls inside it. This was
   tested with an event-driven update graph in the benchmark. From your own Java
   threads, capture `ExecutionContext.getContext()` where it is real and `open()`
   it, the same rule as Python (ledger R6).
9. **Exceptions.** An exception thrown from `onUpdate` fails the listener, in
   Java exactly as in Python. Catch inside, and record failures.
10. **Threads and the GIL.** A Java listener runs on the update thread without
    the GIL. A Python listener holds the GIL for its whole callback.

## 7. Project layout and build (Maven)

The folder follows Maven's standard layout:

```text
hybrid/
  pom.xml                                   Maven build: Deephaven deps "provided", JUnit 5 for tests
  build.py                                  same jar without Maven, against the pip server's own jars
  run.py                                    build, then start the server with the jar and an entry point
  src/main/java/com/acme/hybrid/            Fast, SignalFlipTracker, HybridApp
  src/main/python/hybrid_py.py              the Python-primary app (architecture A)
  src/main/resources/app.d/python/          app-mode entry for A
  src/main/resources/app.d/java/            app-mode entry for B (the loader + Python action)
  src/main/resources/app.d/groovy-console/  entry for B on Groovy-console servers
  src/test/java/com/acme/hybrid/FastTest.java    JUnit unit tests (mvn test)
  src/test/python/bench.py, check_entry.py       integration tests against a running engine
  results/bench.json                        latest benchmark output
  target/                                   build output (git-ignored)
```

- **Dependencies are `provided`.** The server, or the Enterprise worker, already
  has Deephaven on its classpath, so the jar carries only your classes. Match
  `deephaven.version` to the server's Core version. Core+ workers report
  theirs, and it may not be 42.6.
- **`build.py` versus Maven.** `build.py` compiles `src/main/java` against the
  exact jars the pip server runs: no download, no version skew, and it rebuilds
  only when sources change. `mvn package` builds the same jar from Maven Central
  for CI. The POM was not run here, because Maven is not installed on this
  machine.

## 8. Running locally and on Enterprise

**Locally**, from the repo root with the server venv:

```bash
.venv-server/Scripts/python hybrid/run.py --entry python   # architecture A
.venv-server/Scripts/python hybrid/run.py --entry java     # architecture B
```

`run.py` calls `build.py`, then `server/run_server.py --classpath target/hybrid.jar --app-dir src/main/resources/app.d/<entry>`.
The jar must be on the classpath **before** the JVM starts. A running worker
cannot pick up a new jar; restart it.

**On Enterprise** (from the docs, not tested here):

1. Build the jar in CI with `mvn package`, against the plant's Core+ version.
2. Put it on the workers' classpath, using one of these
   ([worker configuration](https://deephaven.io/enterprise/docs/query-management/worker-configuration/)):
    - the PQ's **Extra Classpaths** field (exact paths, no wildcards)
    - a directory configured for the **WorkerKind**
    - the installation's `custom_lib` folder
3. The PQ's script is the entry point: the Python module for A, or the loader
   for B. With `dhfw.meta_import`, both can come from the controller's Git
   repository.

## 9. Testing

| Level | Where | How |
|---|---|---|
| Unit: pure Java functions | `src/test/java` (JUnit 5) | `mvn test`. No engine needed: `Fast` is plain static methods (not run here: no Maven) |
| Equivalence: Java equals Python | `src/test/python/bench.py` | the same inputs give the same values (1,000 rows checked), the same flips (621,778), and null in, null out |
| Integration: both entry points | `src/test/python/check_entry.py <port>` | fields published into the scope; tables tick; Python alerts track Java flips |

For listener logic, the event-driven update graph used in `bench.py` gives
deterministic tests: push rows, `requestRefresh()`, then assert. There are no
sleeps, as in `dhapp`'s test mode.

## 10. Measured performance, and what to move

From `src/test/python/bench.py`, over three runs. Each pair gave identical results.

| Slow node | Python | Java | Ratio |
|---|---|---|---|
| Per-row function, 2,000,000 rows | 1.50–2.01 s (UDF) | 0.31–0.38 s (static method) | **4.7–6.5x faster**; an inline formula took 0.32–0.42 s |
| Stateful listener, 20,000 updates per step | adds 31–32 ms per step | adds 1.6–2.4 ms per step | **13–20x cheaper**; the graph alone took 4.8 ms per step |

What to move, in order:

1. **Can it be built-in operations?** `update_by`, `agg_by`, joins and
   `rolling_formula_*` are already incremental Java and cost nothing to adopt.
2. **Per-row Python functions**: move them to a Java static method, or write
   the math inline in the formula, which needs no jar at all.
3. **Listeners that loop over rows**, especially stateful ones: move them to a
   Java listener plus a `TablePublisher`.
4. **Leave in Python:** rare or small listeners; I/O-bound actions (orders,
   alerts, HTTP), where Java saves nothing; ML; UI; orchestration.

## 11. Limits we hit

- **No Groovy on the pip server.** It runs only Python application scripts, and
  refused a Groovy one: "Cannot instantiate Groovy application on a Python app
  session" (X21).
- **No standalone Java launcher in the pip package** (no `JettyMain`). A
  Java-first *process* needs the `server-jetty-app` distribution or the Docker
  image (X22).
- **`query_library.import_static`** cannot see jars added with
  `extra_classpath`; use fully qualified names (X2).
- **Untested here:** the Maven POM and JUnit run (no Maven installed); the
  Enterprise classpath options; Java-primary on a Groovy-console server.
