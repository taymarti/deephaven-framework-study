# Deephaven as an application framework: onboarding for a new assistant

Read this first. It tells you what this project is, how it unfolded, what we now
believe and why, and where every document, script and result lives.

As of 2026-10-21. Everything marked **Tested** ran on Deephaven Community 42.6.

---

## 1. The situation

The user works at a firm that uses **Deephaven Enterprise (DHE)** heavily. Code runs there as **Persistent Queries (PQs)** on a shared "plant".

The firm also has its own Python **algorithm framework**:
- an asyncio `EventManager` with hooks (`on_initialize`, `on_data`, `on_order_update`, `on_start_of_day`, `on_shutdown`)
- feed tasks (Solace, Kafka, kdb, files)
- a synchronizer that defines checkpoints
- a DAG of computations with callbacks
- side servers: a websocket data API, a diagnostics site and an IPC REPL

The user's boss brought Deephaven in, and Deephaven advertises that you can run arbitrary Python applications as PQs. The user doubted that claim was fully substantiated.

The project's question: **what is Deephaven, really, as an application framework? Where should our code live, and how do we build trading and risk programs on it?** The user wants claims backed by tests, not by marketing or memory.

## 2. How the work unfolded (narrative)

1. **Two UIs on one server.** We built a mock market-making book (`server/app.d/business_logic.py`) and showed it two ways:
   - **deephaven.ui** (Python components rendered server-side, `ui_dashboard.py`)
   - **React** with `@deephaven/jsapi` and `IrisGrid` (`react-client/`)

   This taught the client model: tables travel to browsers as Barrage subscriptions.
2. **The runtime, explained.** A script runs **once** and declares tables. The **update graph** then recomputes what changed, about once a second, in one consistent step ("cycle"). Listeners are the only per-cycle Python.

   We mapped this onto the user's EventManager and synchronizer, and onto Enterprise PQs (each PQ is roughly a Community worker plus Enterprise services). We also covered what happens if you run an unrelated asyncio app inside a PQ.
3. **A ladder of experiments** (`examples/01`–`05`):
   - the lifecycle
   - the declarative DAG replacing `on_data`
   - listeners as the imperative hook (and their gotchas)
   - many feeds arriving at one checkpoint
   - introspection of the engine's own graph, with per-node cost

   The finding: Python listeners were the costliest nodes in the graph, about 195 ms per interval against 3–36 ms for Java operations.
4. **Introspection tooling** (`introspect/`). A module inventories a running app from inside its worker:
   - fields and scope objects
   - every update graph
   - nodes with their cost
   - listeners compared with the handles that can stop them
   - unnamed (leaked) nodes
   - threads

   A client runs it remotely.
5. **Concepts, tested.** We measured scopes, fields, tickets and Barrage (`tests/probe_concepts.py`, `tests/probe_app.d/`):
   - one global scope
   - underscore names are still published as fields
   - export ticket formats
   - shared tickets die with their publisher
   - `bind_table`
   - `dh+plain://` URIs
6. **No Docker; native Windows.** Docker was unavailable, so we ran the pip `deephaven-server` natively on Windows. The docs say it needs WSL. It works with three workarounds (`server/run_server.py`).
7. **Runtime features.** Tested:
   - server executors
   - **event-driven update graphs**: our own code calls `requestRefresh()` to make a checkpoint
   - per-thread execution contexts
   - hosting Deephaven **on a thread of our process** versus as a **subprocess**

   Neither hosting style needs the main thread. Each has costs: a shared GIL, a shared failure domain, `__main__` becoming the console scope, and one server per process.
8. **Documents, a deck, an audit.** We wrote three reference docs and a deck, and kept a ledger of verified facts. A multi-agent audit confirmed 18 errors, all fixed. It ran out of budget before checking 53 further candidates; those became the "Unverified" table (U1–U15) in the ledger.
9. **A programmer's guide** (`docs/Building a Deephaven Application...pdf`):
   - thread swimlane and state-machine diagrams
   - the construct catalog with exact syntax
   - extension points, with Java and Python functions in formulas tested
   - backtesting: TableReplayer, Enterprise replay queries, and an event-driven backtest
   - a worked trading and risk engine (`examples/06`)
   - a concept mapping against QuantConnect LEAN

   The worked engine ran live and as a backtest from the same `build_engine` function, with an identical final book.
10. **Cross-plant data, local testing, and a wrapper.** We worked out how a PQ graph behaves when it mixes local tables with tables fetched from another plant:
    - snapshot: frozen, stops ticking
    - polled: refreshes at your rate
    - Barrage subscription: live, but on two clocks

    We compared the Enterprise "local development" guide (JVM unit tests with a mocked `db`) to our setup (a full Community server). Then we built **`dhfw`**, which lets one codebase run on both runtimes:
    - you write against the Enterprise API
    - on Enterprise, `dhfw` forwards to the real API
    - on Community, it emulates `db`, `remote_table`, `pq://`, system-table logging, controller imports, ACLs and replay mode

    Its Community emulations pass 12/12 tests (`tests/test_dhfw_community.py`). The Enterprise path is untested; there was no plant access.
11. **From toolbox to recipes: `dhapp`.** An application layer on `dhfw`:
    - four roles: source, stage, action, surface
    - three modes: live, backtest, test (feed and step)
    - a `Catalog` that resolves logical table names by location (same PQ, same plant, another plant, laptop)
    - trading and risk `recipes`, standard `schemas`, `store` persistence recipes
    - an automatic deephaven.ui `dashboard`

    The rung-6 engine rebuilt on it passes 8/8 (`examples/07_app_framework.py`): live equals backtest equals rung 6. The live dashboard runs from `examples/mm_app.d/`; in the browser, editing a limit in the grid cleared a breach at the next cycle.

    These layers have their own document, *dhapp and dhfw: Framework Reference*. The code is published at github.com/taymarti/deephaven-framework-study (public).

12. **Ticking remote tables in a local app.** Inside a Community server, `deephaven.barrage.barrage_session(...).subscribe(ticket)` gives a ticking local table from another server (X16). `pydeephaven` can shape the table on the remote side and publish it under a shared ticket, so only that slice travels (X17).

    Lifetimes:
    - an existing subscription survives the publisher's close; a new one fails (X18)
    - dropping the published `pydeephaven` Table object breaks the ticket (X19)

    `dhfw`'s Community `remote_table` now works this way, with anonymous, basic or PSK auth from `DHFW_PQ_MAP` and filters applied remotely (X20).

    `pydeephaven-ticking` is the alternative for plain Python processes with no engine. It delivers callbacks, not tables, and has Linux-only wheels.

13. **Python and Java in one project** (`hybrid/`, Maven layout; read `hybrid/GUIDE.md`). `build.py` compiles `src/main/java` against the server's own jars into `target/`; `pom.xml` does the same with Maven. `run.py` builds and then starts with the jar on the classpath, using either entry point:
    - Python: the graph in Python, calling Java nodes
    - Java: `HybridApp.start()` builds the graph; a loader publishes it into the scope and adds a Python action

    Measured:
    - a per-row function was 4.7–6.5x faster in Java (X24)
    - a stateful listener was 13–20x cheaper in Java (X25)
    - Java formula functions must handle Deephaven's null sentinels (X27); listeners attached in app scripts need `do_replay=True` (X28)

    The pip server refuses Groovy app scripts (X21) and ships no Java launcher (X22). On Enterprise, jars go on Extra Classpaths, a WorkerKind directory or `custom_lib` (X26, Docs).

14. **A complete app in three languages, shipped as one wheel** (`desk-app/`; read `desk-app/README.md`). An options risk desk:
    - **Python** owns the app: feed, graph, alert action, deephaven.ui ops dashboard, both entry points, packaging
    - **Java** owns the CPU-hot nodes: Black-Scholes per row (`Pricing`) and a stateful breach tracker (`LimitBreachTracker`)
    - **React 19 + TypeScript** is the trader UI: live grids over the JS API, and forms that write to input tables

    One Maven-style tree holds three build units (Maven, npm + Vite, hatchling via uv). The wheel bundles the jar and the web build through `force-include`. Deploying is `pip install` into a fresh venv plus two console scripts, `dh-desk-server` and `dh-desk-web` (static files plus a reverse proxy for `/jsapi`, gRPC-web and websockets).

15. **Pixi as the monorepo orchestrator** (`pixi.toml` at the root; read `MONOREPO_TOOLING.md`). Every toolchain is pinned from conda-forge, and per-project environments are built from features. Other features in use:
    - a `[workspace.dependencies]` pool
    - solve-groups
    - task inputs and outputs (cached)
    - environment-pinned `depends-on` for the repo-level `build`, `check` and `ci`
    - typed task args

    `pixi run ci` passes: ruff, tsc, JUnit, the build, then a smoke test that installs the wheel into a fresh venv and checks it end to end (9/9).

    `MONOREPO_TOOLING.md` also compares Pixi with Pants, confirming that Pants' edge is code-level targets, dependency inference, target selection and resolves. Pixi has resolves natively, as environments and solve-groups. The acchapm1 tutorials' `members = [...]` monorepo layout is rejected by Pixi 0.81.

## How to work on dhapp and dhfw

- **Stages stay pure and table-native.** No per-row Python; recipes take tables and return tables.
- **New Enterprise-vs-Community differences go into `dhfw`**, never into app code. Each emulation states its limits in its docstring and in `dhfw.LIMITATIONS`. An unsupported call raises `UnsupportedOnCommunity`.
- **Location lives in the `Catalog`.** App code never names a host, a PQ or a plant.
- **Every change must keep both suites green:** `examples/07_app_framework.py` (8/8) and `tests/test_dhfw_community.py` (12/12). Run them with `.venv-server`.
- **Record new facts** in `VERIFIED_FACTS.md` with an ID and their evidence.

## 3. What we now believe (the short list)

- **Deephaven is a dataflow engine, not an event loop.** Put logic in table operations. Use listeners sparingly: they are Python, run inside the cycle, and cost GIL time.
- **One cycle is one consistent checkpoint**, about 1 s by default. Rows pushed between cycles wait for the next one. An **event-driven update graph** lets our code decide when a checkpoint happens (R8, X7).
- **Execution contexts are per thread.** Threads you start yourself need a context handed to them (R6).
- **Hosting:**
  - table-shaped work belongs in PQs
  - stateful applications sit beside them: as a client, as a subprocess service, or with Deephaven on a thread of our process (R9–R14)
- **Extending it:**
  - Java and Python functions work inside formulas
  - your own operation library works by composing built-ins
  - custom sources: `table_publisher` in Python, `StreamPublisher` in Java (Docs)
  - **there is no public interface for a new incremental table operation**
- **Backtesting:**
  - the same graph code runs live, replayed or backtested, *if the graph is a function of its source tables*
  - Enterprise replay queries simulate the clock (Docs)
  - Community `TableReplayer` replays at 1x speed, and `now()` stays on wall-clock time
  - there is no fill, broker or portfolio model, unlike LEAN
- **Across workers and plants,** each side keeps its own clock. Subscriptions are live but not consistent with each other. Snapshots are frozen.

## 4. Evidence conventions

- **`VERIFIED_FACTS.md` is the source of truth.** Each fact has an ID:
  - S: scopes and fields
  - T: tickets
  - R: runtime
  - G: graph and introspection
  - P: platform
  - X: extensions and replay
  - U: open questions
- Each fact carries one of these labels:
  - **Tested** (also written "Verified"): observed in a test in this repo
  - **Source**: read in the installed 42.6 code
  - **Docs**: Deephaven documentation only
- **Corrections** to earlier claims are listed in the ledger. Read them before repeating any claim from older material.
- **The U table** (Unverified) lists claims the audit flagged but never checked. Treat them as open.

## 5. Environment and how to run things

- **Windows 11 native.** Java is PyCharm's bundled JBR 17: `C:\Program Files\JetBrains\PyCharm 2023.3.3\jbr` (it includes `javac`). Set `JAVA_HOME` to it.
- **Two virtual environments:**
  - `.venv` (client tools, pydeephaven)
  - `.venv-server` (deephaven-server 42.6, deephaven-plugin-ui 0.42.2, plotly-express 0.20.1)
- **Server:** `.venv-server\Scripts\python server\run_server.py [--app-dir ...] [--psk KEY]`, port 10000. The probes use embedded servers on ports 10002–10005.
- **Windows gotchas** (the first three are fixed inside `run_server.py`):
  - JVM DLL folders must be on `PATH`
  - the web storage directories must be relative
  - `JAVA_HOME` must be set
  - integer type hints on Python functions used in formulas are rejected
  - `query_library.import_static` cannot see jars added with `extra_classpath`
  - parquet needs `file:///` URIs
- **Pixi** (0.81, `~/AppData/Local/pixi/bin/pixi.exe`) provides its own JDK 17, Maven, Node 22, Python 3.12, uv and ruff for `desk-app`. No system JDK is needed there.
- **Docker** files exist (`docker-compose.yml`, `server/Dockerfile`), but Docker was unusable on this machine.

## 6. Index of documents

The same three living docs also exist as Claude Docs; the PDFs are snapshots. The doc names below are the PDF filenames under `docs/`.

| Document | What it is for |
|---|---|
| `Deephaven as an Application Framework Findings and Guidance.pdf` | The original consolidated write-up: runtime, the two UI routes, gotchas, Enterprise PQ considerations, placement guidance, vendor questions |
| `Deephaven Concepts Scopes, Fields, Tickets and Barrage.pdf` | Glossary and tested claims: global scope, application mode, fields, tickets, Barrage, URIs |
| `Anatomy of a Deephaven Application.pdf` | The runtime in space and time, threads, and hosting on a thread vs. as a subprocess, with measurements |
| `Building a Deephaven Application A Programmer's Guide.pdf` | The practical guide to the engine: diagrams, construct syntax, extending, backtesting, the worked engine, the LEAN comparison, three-tier testing, and summaries of `dhfw` and `dhapp` |
| `dhapp and dhfw Framework Reference.pdf` | The reference for building on our two layers: a layer diagram, quick start, concepts (roles, modes, catalog, health), API, environment variables and deployment, cookbook, limits and evidence |
| `Verified Facts Ledger.pdf` | `VERIFIED_FACTS.md` rendered: every claim with its evidence, the corrections, and the U table |
| `Repository README.pdf`, `Examples README.pdf` | How to run the two UI routes and the experiment ladder |
| `Deephaven as an Application Framework.pptx` | 23-slide presentation deck, with speaker notes |
| `docs/_text/*.txt` | Plain-text extracts of every PDF, for quick searching |

## 7. Index of code and results (under `repo/`)

| Path | What it is |
|---|---|
| `README.md`, `VERIFIED_FACTS.md`, `LLM_ONBOARDING.md` | Overview, the ledger, this file |
| `server/run_server.py` | Runs the pip server natively (Windows workarounds, `--psk`, `--app-dir`) |
| `server/app.d/` | Application-mode app: `business_logic.py` (mock book), `ui_dashboard.py` (deephaven.ui), `introspection.py` (opens the ancestors log first), `book.app` |
| `server/requirements-server.txt`, `setup_wsl.sh`, `start.sh`, `wsl_check.sh`, `Dockerfile`; `docker-compose.yml` | Ways to install or run the server |
| `react-client/` | The React route: `App.tsx`, `LiveGrid.tsx` (IrisGrid), `hooks.ts` (viewport plus updates), Vite config, module-loader shim |
| `examples/01`–`05_*.py`, `run.py` | The experiment ladder; `run.py` sends a script to the server |
| `examples/06_trading_engine.py` (+ `.json`) | The worked engine, live vs. backtest; result: identical book and risk |
| `examples/pretty_graph.py`, `dump_*.py`, `*.svg`, `*.dot` | Update-graph pictures with per-node cost |
| `examples/probe_*.py` | Small introspection probes |
| `introspect/dh_introspect.py`, `dh_introspect_client.py` | Introspection module and its remote client |
| `tests/probe_concepts.py`, `probe_app.d/` | Scope, field and ticket tests |
| `tests/probe_runtime_features.py`, `probe_event_driven_clock.py` | Executors and an event-driven clock |
| `tests/embedded_thread_demo.py` (+ `_client.py`, `_result.json`) | Deephaven on a thread of our process |
| `tests/host_service_demo.py` | Deephaven as a subprocess service |
| `tests/probe_introspection.py`, `introspection_report.json` | Introspection end to end, with a saved report |
| `tests/probe_framework_constructs.py` (+ `.json`), `java/com/acme/Risk.java`, `acme-risk.jar` | Java and Python functions in formulas, sources, replay, backtest |
| `dhfw/` | The runtime wrapper: `runtime`, `database` (`db`), `remote`, `systable`, `controller`, `acl` |
| `tests/test_dhfw_community.py` (+ `.json`) | 12/12 Community checks of `dhfw` (the test server uses PSK auth) |
| `tests/probe_remote_ticking.py` (+ `.json`) | Ticking remote tables in a local server: Barrage, pydeephaven-shaped shared tickets, lifetimes (needs a server with ticking tables on :10000) |
| `hybrid/` | One project in Python and Java, Maven layout: `GUIDE.md` (how to combine them, both directions), `pom.xml`, `src/main/java` (Fast, SignalFlipTracker, HybridApp), `src/main/python`, `src/main/resources/app.d/*`, `src/test/java` (JUnit), `src/test/python` (bench, check_entry), `results/bench.json`, `build.py`, `run.py` |
| `desk-app/` | Python + Java + React app in one wheel: `pom.xml`, `package.json`, `tsconfig*.json`, `vite.config.ts`, `pyproject.toml`, `src/main/{java,python,web}`, `src/test/{java,python}` (JUnit; `smoke.py` + `smoke_check.py`), `README.md` |
| `pixi.toml`, `pixi.lock`, `MONOREPO_TOOLING.md` | The monorepo's toolchains and tasks (`pixi task list`), and the Pixi features used plus the Pixi vs Pants comparison |
| `dhapp/` | The application layer: `app` (roles, modes, health), `catalog`, `recipes`, `schemas`, `store`, `ui` |
| `examples/mm_app.py`, `07_app_framework.py` (+ `.json`) | The engine on `dhapp`, run live, backtest and test: 8/8 |
| `examples/mm_app.d/` | Application-mode demo: the app live with a synthetic feed and `mm_dashboard` |
| `deck/build_deck.js`, `render.ps1`, `sheet.py`, `assets/` | Deck generator (pptxgenjs) and visual QA through PowerPoint |
| `tools/build_deliverables.py` | Builds the PDF and text deliverables |

## 8. Working agreements (how the user likes to work)

- Claims must be backed by a test, the source, or the docs, and labelled as such. Run a probe rather than assert.
- Be concise. Lead with the answer and its number.
- The user is thinking about the future state at work, where deployments happen on Enterprise. Community is for local development and testing.
- The audit was stopped because it cost too much. Don't fan out many agents without asking.

## 9. Open threads

- Run `tests/test_dhfw_community.py` and `examples/07_app_framework.py` on a Core+ worker with `DHFW_RUNTIME=enterprise`, to validate the forwarding. The `auth_context` function name and the `for_remote_cluster` credentials in particular are unconfirmed.
- Add a laptop-to-plant catalog binding through the Core+ Python client.
- Persist Community `state_table` contents to parquet, so local edits survive restarts.
- The dashboard's KPI cards are clipped in small windows; the panels can be resized.
- U2 and U3: re-run the GIL-lag and startup-speed measurements with more samples and a baseline.
- Check cross-plant `remote_table` reconnect behaviour on the plant.
- Questions for the vendor:
  - Are event-driven update graphs supported inside PQs?
  - What isolation, health checks and shutdown hooks are available?
  - Is there a public interface for custom table operations?
