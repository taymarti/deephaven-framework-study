# desk-app: a complete Deephaven application in Python, Java and React

An options risk desk, built from three languages, each where it is strongest. It ships as **one Python wheel**:

- **Build:** `pixi run desk-app-build`, from the repo root.
- **Deploy:** `pip install` the wheel into a fresh virtual environment, then run its two entry points.

```text
 browser ──► dh-desk-web (:4010)                     dh-desk-server (:10000), one process
            ├ React trader app (static build)       ┌─────────────────────────────────────────────┐
            └ proxy /jsapi, gRPC-web, websockets ──►│ JVM: Deephaven engine + server               │
                                                    │   update graph, Barrage, input tables        │
                                                    │   Java unit (bundled jar): Pricing per row,  │
                                                    │     LimitBreachTracker on the update cycle   │
                                                    │ CPython (embedded): the dh_desk package       │
                                                    │   feed thread, graph, alert action,          │
                                                    │   deephaven.ui ops dashboard (/iframe/widget) │
                                                    └─────────────────────────────────────────────┘
```

## Why three languages, and who does what

| Language | Role in this app | Why it is the right tool here |
|---|---|---|
| **Python** (`src/dh_desk`) | Owns the application: the market-data feed, the table graph, the alert action, the internal ops dashboard (deephaven.ui), both entry points, the packaging | Deephaven's application language: the graph is a short declarative script, feeds and SDKs are Python libraries, deephaven.ui builds an operator view in minutes with no front-end build, and pip is the deployment vehicle |
| **Java** (`java/`) | The CPU-hot nodes: Black-Scholes price and Greeks per row (`Pricing`), and a stateful breach tracker on the update cycle (`LimitBreachTracker`) | Runs as native engine code with no GIL. Per-row functions were 4.7–6.5x faster and stateful listeners 13–20x cheaper than Python in `hybrid/`'s benchmark |
| **React + TypeScript** (`web/`) | The trader-facing web app: live risk and book grids, a limit editor, an order ticket | Your own UX, branding and routing; forms that write back into Deephaven; deployable as static files. It talks to Deephaven only through the JS API |

Some things are deliberately *not* in a given language:

- **Python does no per-row math and no row loops.** The Java functions and the engine's own operations do that.
- **Java does no I/O.** Alerting is Python's job, because it is I/O-bound and Java would save nothing.
- **React holds no state the server should own.** It writes tickets and limits into input tables, and the graph recomputes from them like any other source.

## What it does

```text
spot feed (Python thread) ─last_by─► spot ─┐
vols (static) ─────────────────────────────┼─► book: positions + Java Pricing.price/delta/gamma/vega per row
tickets (input table; React's order ticket) ─agg_by─► positions ─┘       │ agg_by Desk
limits (keyed input table; React's limit editor) ───────────────► risk: delta $ vs limit, Utilization, Breach
                                         Java LimitBreachTracker ◄────┘ (state on the update cycle)
                                                  └─► breach_events ─► Python alert action ─► alerts
```

Published tables (the console scope, opened by name from React, Python clients and the IDE):

- `spot`, `positions`, `book`, `risk`
- `limits`, `tickets`
- `breach_events`, `alerts`
- `desk_ops`, the ops dashboard

Try it:

1. Lower a desk's limit in the React app. The Java tracker emits `BREACH`, and the Python action writes an alert.
2. Raise it again. The tracker emits `CLEAR`.
3. Book a ticket. Positions, Greeks and risk update at the next cycle.

## Project layout: one project, three build units

Each build unit uses **its own ecosystem's standard layout**. Nothing is bent to match another
language:
- **Python** is the host, because it owns the deliverable (the wheel). It uses the standard src
  layout at the project root: `pyproject.toml`, `src/dh_desk/`, `tests/`, and builds into `dist/`.
- **Java** is a Maven module in `java/`: `pom.xml` at the module root, above `src/main/java` and
  `src/test/java`, and it builds into `target/`. In Maven's convention, `java` is the leaf under
  `src/main/`, not a top-level folder. The `java/` directory here is the module, as in any multi-module
  or multi-language repo.
- **Web** is a standard Vite app in `web/`: `package.json`, `vite.config.ts`, `tsconfig*.json`,
  `index.html` and `src/`, and it builds into `dist/`.

```text
desk-app/
  pyproject.toml        Python unit (hatchling): the wheel, bundling the other units' outputs
  src/dh_desk/          server.py, web.py (entry points), app.py, feeds.py, ops_ui.py, resources.py
  tests/                smoke.py (deploy + run), smoke_check.py (end-to-end assertions)
  dist/                 the wheel (git-ignored)
  java/                 Java unit (Maven module)
    pom.xml
    src/main/java/com/acme/desk/   Pricing.java, LimitBreachTracker.java
    src/test/java/com/acme/desk/   PricingTest.java (JUnit 5, run by `mvn package`)
    target/dh-desk.jar             (git-ignored)
  web/                  web unit (npm + Vite, React 19 + TypeScript)
    package.json, package-lock.json, vite.config.ts
    tsconfig.json (+ .app, .node)  project references: browser code vs build config
    index.html
    src/                main.tsx, App.tsx, deephaven.ts, hooks.ts, format.ts, components/
    dist/               (git-ignored)
```

The wheel takes the other units' outputs straight from `java/target/dh-desk.jar` and `web/dist`,
through hatchling's `force-include`, and places them inside the package as
`dh_desk/_bundle/{java,web}`. There is no copy step. At runtime, `dh_desk.resources` finds them in
the installed package, or in the units' build folders when running from source.

## Build: Pixi orchestrates, each unit uses its own toolchain

The repo-root `pixi.toml` pins every toolchain from conda-forge in `pixi.lock`: JDK 17, Maven 3.9,
Node 22, Python 3.12 and uv. A checkout therefore builds the same way anywhere `pixi` is installed.
Pixi tasks chain the units together:

```text
desk-app-java ──────────────────────┐   mvn -B package           (compile, JUnit, jar)
_desk-app-web-deps ─► desk-app-web ─┼─► desk-app-wheel ─► desk-app-build   (repo: pixi run build)
  npm ci               tsc -b && vite build   uv build --wheel (hatchling)
                                    └─► desk-app-smoke / desk-app-install
desk-app-lint (ruff + tsc, in the desk-app-ci environment)                  (repo: pixi run check)
```

Each task declares `inputs` and `outputs`, so a rerun skips any unit whose sources have not changed.
The `desk-app-ci` environment shares a solve-group with `desk-app`, so it has the same versions
plus ruff. See [`../MONOREPO_TOOLING.md`](../MONOREPO_TOOLING.md) for every Pixi feature used.

```bash
pixi run desk-app-build      # all units, then the wheel in desk-app/dist/
pixi run ci                  # lint + type-check, build (with JUnit), smoke deploy: what CI runs
pixi run desk-app-smoke      # fresh venv, install the wheel, run both entry points, end-to-end checks
pixi run desk-app-java       # one unit at a time
pixi run desk-app-web-dev    # hot-reloading React against a running server
pixi run desk-app-clean      # delete dist/, java/target/, web/dist/
```

## Deploy: install the wheel, run two entry points

Requirements on the target machine:
- Python 3.10 or later
- a **Java 17+ JDK** in `JAVA_HOME` (Deephaven compiles formulas at runtime, so a JRE is not enough)
- network access to PyPI, for the wheel's declared dependencies: `deephaven-server`, `deephaven-plugin-ui` and `aiohttp`

```bash
python -m venv desk-env
desk-env/bin/pip install dh_desk-0.1.0-py3-none-any.whl     # Windows: desk-env\Scripts\pip
desk-env/bin/dh-desk-server --port 10000                     # Deephaven + the app
desk-env/bin/dh-desk-web --port 4010 --dh-url http://localhost:10000
```

Then open:
- **the trader app** at http://localhost:4010
- **the ops dashboard** at http://localhost:10000/iframe/widget/?name=desk_ops
- **the Deephaven IDE** at http://localhost:10000/ide/

`pixi run desk-app-install` does the same into `desk-app/.venv`. Then two tasks start the entry points; both take typed args:
- `pixi run desk-app-run-server [port] [heap]`, defaults `10000`, `2g`
- `pixi run desk-app-run-web [port] [dh_url]`, defaults `4010`, `http://localhost:10000`

## Design notes

- **One origin for the browser.** `dh-desk-web` serves the React build and reverse-proxies `/jsapi`,
  `/js-plugins`, `/arrow.*` and `/io.deephaven.*` (HTTP and websockets) to the server. So there is no
  CORS, one port to expose, and the JS API module is always the server's own version. The Vite dev
  server proxies the same paths.
- **No `@deephaven` React packages.** The app imports `/jsapi/dh-core.js` at runtime and uses
  `CoreClient`, `getObject`, viewports and `inputTable().addRow` directly, with React 19's `use()`
  for the connection and table handles, and `useActionState` for the forms. `@deephaven/jsapi-types`
  supplies the types only.
- **Java boundary rules**, from `hybrid/GUIDE.md`:
  - call Java by its fully qualified name in formulas
  - a null cell arrives as `QueryConstants.NULL_DOUBLE`, not NaN, so return the sentinel
  - keep references to listeners and publishers
  - attach Python listeners with `do_replay=True`
  - each listener-to-publisher hop adds one cycle
- **Execution context.** `dh-desk-server` builds the graph on the thread that started the server,
  which holds the real context. It then publishes into that process's `__main__`, which is the
  console scope.

## Limits

- **Authentication:** anonymous by default. `dh-desk-server --psk` enables a pre-shared key, but the
  React app logs in anonymously only. Real authentication would need a login step in `deephaven.ts`.
- **Storage:** input tables are in memory, so tickets and limits reset on restart. On Enterprise they
  would be persistent input tables; see `dhfw` and the Framework Reference.
- **Market data:** the spot feed is synthetic, and volatilities are static.
