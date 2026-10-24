# Monorepo tooling: Pixi as used here, and how it compares with Pants

This repo uses Pixi as its root toolchain manager and task orchestrator (`pixi.toml`, `pixi.lock`).
`desk-app/` is the first polyglot project in it: Java, React/TypeScript and Python, shipped as one wheel.
This page covers three things:

1. Which Pixi features the setup uses, and why
2. What we deliberately left out
3. How Pixi compares with Pants, a build system aimed at the same polyglot-monorepo problem

The sources are the current Pixi docs (pixi.prefix.dev/latest), Pixi 0.81 run locally, and the Pants
docs (pantsbuild.org/stable). The acchapm1 Pixi tutorials were also reviewed. They target Pixi 0.41–0.44
and are out of date in places, as noted below.

## 1. Pixi features demonstrated in `pixi.toml`

| Feature | Where | What it shows |
|---|---|---|
| Conda-forge toolchains, locked per platform | `[workspace]` `platforms`, `pixi.lock` | JDK 17, Maven, Node 22, Python 3.12, uv and ruff are pinned for win-64, linux-64 and osx-arm64. A checkout needs only `pixi`, with no system JDK or Node. |
| `requires-pixi`, `channel-priority` | `[workspace]` | Reproducibility guards for every contributor and CI machine |
| **Workspace dependency pool** | `[workspace.dependencies]` + `{ workspace = true }` | Each toolchain version is pinned once for the whole repo. Every feature opts in, so a JDK bump is a one-line change. |
| **Features** (composition) | `jvm`, `node`, `py`, `lint`, and one per project | Toolchains are reusable building blocks. A project's environment lists the ones it needs. |
| **Environments** with `no-default-feature` | `[environments]` | One environment per project, containing only its toolchains |
| **Solve groups** | `desk-app` + `desk-app-ci` share `solve-group = "desk-app"` | The CI environment adds ruff but keeps every shared package at exactly the build environment's version. One lockfile, consistent resolves. |
| **Activation env** | `[feature.node.activation.env]`, `[feature.py.activation.env]` | Per-toolchain settings, such as quiet npm and the uv link mode, applied in every environment that uses the feature |
| Tasks with **`inputs`/`outputs`** | each build-unit task | Fingerprint caching: `pixi run build` skips any unit whose sources, outputs, command and environment are unchanged. This is incremental builds across Maven, npm and uv. |
| **`depends-on`** chains | java, web → wheel → install/smoke | The build DAG across three ecosystems |
| **Environment-pinned `depends-on`** | `[tasks.build]`, `check`, `ci` | Repo-level aliases fan out to each project's tasks *in that project's environment*. This is the monorepo orchestration idiom. |
| **`default-environment`** | every project task | `pixi run desk-app-java` never prompts, even though the feature belongs to two environments |
| **Typed task `args`** + **MiniJinja** | `desk-app-run-server` (`port`, `heap`), `desk-app-run-web` (`port`, `dh_url`) | `pixi run desk-app-run-server 10030 4g`. Args have defaults and render into `cmd`. |
| Task `env`, `cwd`, `description` | throughout | `pixi task list` is the catalog of what the repo can do |
| **Hidden tasks** (`_` prefix) | `_desk-app-web-deps` | Internal steps that stay out of `pixi task list` |
| **deno_task_shell** | `desk-app-install` (`&&`, a glob), `desk-app-clean` (`rm -rf`) | The same task strings run on Windows, Linux and macOS |
| Alias tasks | `build`, `check`, `ci` | Tasks with no `cmd`, only dependencies |

Commands people actually use:

```bash
pixi task list
pixi run build          # every project
pixi run ci             # lint + type-check, builds (with JUnit), smoke deploy of every project
pixi run desk-app-run-server 10030
pixi list -e desk-app   # the resolved toolchain for one project
pixi tree -e desk-app openjdk
```

Gotcha found while building this: a pure alias task (no `cmd`) cannot set `default-environment`. When
the alias's feature is in several environments, give it a one-line `cmd`. `desk-app-build` does that.

### Deliberately not used

- **`pixi-build`** (`[package]`, build backends, `[dev]`, inline packages, `pixi publish`). It is the
  native way to model packages and the dependencies between them. But it has three problems here:
  - It builds **conda packages**, and our deployable is a pip wheel installed into a plain venv.
  - It is still a preview feature (`preview = ["pixi-build"]`), and the docs warn it will change.
  - It has no Java or Node backend. The backends are cmake, python, rust, ros, r, mojo, and
    rattler-build, which takes a raw `recipe.yaml`. Wrapping Maven and npm in a rattler-build recipe
    would be a hack.

  If the firm distributed through a conda channel, `pixi-build-rattler-build` plus `pixi publish`
  would be the natural next step.
- **`[target.<platform>]`** and platform branches in task templates. Nothing in desk-app differs by OS.
  The tools are the same everywhere, and deno_task_shell handles the shell differences.
- **`pixi-pack` / containers.** The deployment unit is the wheel. A pixi-packed environment would be
  an alternative way to ship the JDK alongside it.

### Corrections to the acchapm1 tutorials (they are based on Pixi ~0.41–0.44)

- **`[project]` is now `[workspace]`.** The old name is still accepted for compatibility.
- **The "Workspace / Monorepo" section is not valid Pixi.** It uses `members = ["packages/*"]` plus
  per-package `[project]` manifests. Pixi 0.81 rejects that layout: `'members' was not expected here`.
  Pixi has no member discovery for environments or tasks. The real options are:
  - **one root manifest** (this repo), or
  - **separate workspaces** per directory, each with its own lock, run with
    `pixi run --manifest-path <dir>/pixi.toml` or registered with `pixi workspace register`, or
  - **pixi-build packages** (`[package]` in sub-directories) that the root workspace depends on by
    `path`. These are found by walking the directory tree, and only their `[package]` section is used.
- **The newer features are missing from the tutorials:** typed task `args`, MiniJinja templating,
  `default-environment`, environment-pinned `depends-on`, `[workspace.dependencies]`,
  `exclude-newer`, and inline and `[dev]` packages.
- **Features and solve-groups** are explained correctly.

## 2. Pixi vs Pants

**The short version:** Pants is a **build system** that models your *code* as a graph of targets.
Pixi is an **environment manager with a task runner** that models your *toolchains and commands*.
Your assessment is right. Pants' defining strengths are generic, language-aware source and test
targets; dependency inference; target selection fed to any goal; and multiple resolves.

Pixi's polyglot support works at a different layer. It understands *packages and environments* (any
conda package: JDK, Node, compilers, R, CUDA). It does not understand *source code*. It delegates
compiling, testing and packaging to each ecosystem's own tool.

| Capability | Pants | Pixi | Pixi: natural idiom or hack? |
|---|---|---|---|
| **Generic source and test targets** | `python_sources`, `python_tests`, `java_sources`, `junit_tests`, `javascript_sources`, `files`, `resources`, `target`; generated per file, with `__defaults__`, `overrides`, `pants tailor` | None. The unit is a **task** (a command), not a target. `inputs` globs exist only for cache fingerprints. | Modelling "test targets" as one task per suite is natural but coarse. Per-file targets do not exist. |
| **First-party dependency inference** | From imports (Python, JVM, JS, Go, shell); `!`/`!!` exclusions | None. Task order is explicit `depends-on`. | Explicit `depends-on` is natural, but it is between *tasks*. Between packages, `pixi-build` path dependencies give an explicit (not inferred) graph. That is natural but preview-only, and conda only. |
| **Third-party dependency resolution** | Per-language lockfiles (pex/pip, Coursier, npm/pnpm/yarn) | **Its core strength.** A SAT solver over conda plus PyPI (uv), one multi-platform lockfile, and the toolchains resolved too (JDK, Node, compilers) | Natural. It is arguably broader than Pants, since Pants downloads tools per subsystem rather than solving them. |
| **Target selection fed to goals** (`test`, `lint`, `package`, …) | Address specs `dir::`, `dir:name`, file globs, `--changed-since`, `--changed-dependents=transitive`, `--tag`, `--filter-*`, `--spec-files`, `pants dependents` | None. You choose *task names* and *environments*. Subsets within a task come from the underlying tool's own args (`pixi run test tests/foo -- -k bar`). | Task names, typed args, aliases and environment-pinned `depends-on` are natural. "Only what changed" comes from `inputs`/`outputs` caching, which is natural but local and per task. git-diff-driven selection would be a **hack** (a script task computing changed directories). |
| **Multiple resolves** | `[python.resolves]`, `resolve=` per target, `parametrize(resolve=...)`; JVM resolves | **Yes.** Each environment is its own resolve in the one lockfile. `solve-group` makes several environments share one. Running a task under several environments (`pixi run -e py311 test`, a feature in a matrix of environments) is the `parametrize` analogue. | **Natural.** This is the closest one-to-one match between the tools. |
| Per-target parametrization | `parametrize()`, a Cartesian product of targets | Environments as a matrix, plus typed task args | Natural for environment matrices. There is no per-target notion. |
| Hermetic sandboxed execution | Each process runs in a sandbox with declared inputs only | No. Tasks run in the working tree, isolated only by environment. `clean-env` is Unix-only. | n/a |
| Caching | Fine-grained, content-addressed, **remote cache and remote execution** | Task-level fingerprints, local only (`.pixi/`) | Natural, but coarser and not shared |
| Parallelism | Concurrent rules across the graph | `depends-on` runs **sequentially** (per the docs) | n/a |
| Extensibility | Plugin rule API (Python async rules); `adhoc_tool`/`system_binary` for tools with no backend | Tasks *are* the extension point. Any command works. Build backends exist for packages. | Natural, and much lower ceremony |
| Who owns the build | **Pants replaces** Maven, npm and pip workflows with its own goals (e.g. JVM via Coursier with no Maven; JS backend in **beta**) | **Each ecosystem keeps its own tool.** `pom.xml`, `package.json` and `pyproject.toml` stay idiomatic. | n/a |
| Platforms | Linux and macOS; **Windows only through WSL 2** | **Native Windows**, Linux and macOS | n/a |
| Config surface | `pants.toml` plus BUILD files everywhere | One `pixi.toml`, which can grow large. There is no `include` or member manifest for tasks. | Splitting it requires separate workspaces, a natural but fragmenting choice |

### How Pants actually runs Python and Java: standard tools, with Pants as the build tool

Pants does not reimplement compilers, resolvers or test runners. It downloads pinned versions of the
standard ones. Each is a "subsystem" with its own version and lockfile, which Pants supplies by
default and you can override. Pants runs them in sandboxes on the targets you selected, and caches
each run by its inputs.

What Pants replaces is the **build tool's** job: Maven or Gradle, `pip install` into a venv, or
invoking `setup.py`. That job is working out what to compile or test, in what order, what changed,
and how to package it. Those decisions move into Pants' rules.

| Step | Python in Pants | Java in Pants |
|---|---|---|
| Toolchain | The interpreter is discovered on a configured search path (system, pyenv). Interpreter constraints are set per resolve. | The **JDK is fetched by Coursier** (`[jvm].jdk = "temurin:…"`, or `jdk=` per target) |
| Third-party resolution, lockfiles | **Pex**, which drives **pip**. `pants generate-lockfiles` runs Pex's lock command and writes one lockfile per resolve. | **Coursier** ("a dependency resolver for the Maven ecosystem") resolves `jvm_artifact` targets, with one lockfile per `[jvm].resolves` entry. `jvm_artifacts()` can read the dependency list *out of* a `pom.xml`, but Maven itself never runs. |
| First-party dependency graph | Inferred from `import` statements (Pants' own parser) | Inferred from `import`s and the symbols a class uses (Pants' own Java parser) |
| Compile or check | No compile step. `check` runs **mypy** or **pyright** as tools. | **javac** from the fetched JDK, run per inferred unit in a sandbox. Nailgun keeps compilers warm (JDK 17 or older). Scala uses `scalac`, Kotlin `kotlinc`. |
| Test | Builds a **PEX** of the test's sources and requirements, then runs **pytest** inside it. pytest is a tool with its own lockfile. | The **JUnit Platform console launcher** (`junit-platform-console` with the Jupiter and Vintage engines, from a Pants-supplied lockfile) |
| Lint, format | ruff, black, isort, flake8 and others, each a tool PEX, run only on the selected files | google-java-format, scalafmt and similar, as tools |
| Package | **`pex_binary`** builds a single-file Python executable. **`python_distribution`** builds wheels and sdists, with Pants as the **PEP 517 frontend** for your `[build-system]` backend (the docs name setuptools, flit and poetry-core), or with a generated `setup.py`. | **`deploy_jar`**, a fat jar of the classes plus third-party jars with a `main` |

**What this would mean for desk-app.** This mapping is not tested; it is how the pieces would line up.
- The `pom.xml` would go. In its place come `java_sources`, `junit_tests` and `jvm_artifact` targets
  for the Deephaven jars, with Coursier resolving them and javac compiling them.
- The React build would be a `package_json` target with a build script, using the JS backend, which
  is in beta.
- The wheel would be a `python_distribution`. The jar and the web build would become its resources
  through `adhoc_tool` outputs or the wrapper targets, because Pants' own graph would carry the files
  where hatchling's `force-include` does today.
- Contributors would run `pants test ::`, not `mvn package` or `npm run build`.

Pixi works one level up. It provides the build tools themselves (Maven, npm, uv) and runs them. Those
tools then call javac, Surefire, Vite and hatchling, exactly as each ecosystem's documentation describes.

**Pixi does cover some of the Pants list**, mainly:
- third-party resolution (it is stronger at it)
- multiple resolves (environments and solve-groups, natural)
- typed subsets through task args and aliases (natural)
- incremental execution through task caching (natural, but local)

**It does not have:**
- code-level targets
- dependency inference
- `--changed-since` style selection
- sandboxing
- remote caching
- parallel task execution

Imitating these would mean hand-written scripts, which would be hacks.

**When each fits:**
- **Pants** pays off when one team owns a large, mostly Python, JVM or Go codebase and wants
  affected-only CI, remote caching and one interface over every language. It is willing to give up
  Maven and npm conventions and Windows-native development in exchange.
- **Pixi** fits a repo of independent projects in different ecosystems, a Windows workforce, conda
  dependencies (CUDA, compilers, JDK), and teams who want `mvn`, `npm` and `uv` to keep working exactly
  as documented. That describes this repo.

The two are not exclusive. A Pants repo can use Pixi to provision interpreters and system toolchains.
