# hybrid: one Deephaven project, Python and Java, either as the entry point

Write the app in Python and move the slow nodes to Java, or write it in Java and
add Python around it. **Start with [GUIDE.md](GUIDE.md)**, which teaches both
directions with the code in this folder.

```bash
# from the repo root, with the server venv
.venv-server/Scripts/python hybrid/run.py --entry python      # A: graph in Python, Java hot nodes
.venv-server/Scripts/python hybrid/run.py --entry java        # B: graph in Java, Python actions
.venv-server/Scripts/python hybrid/src/test/python/bench.py   # Python vs Java, measured
.venv/Scripts/python hybrid/src/test/python/check_entry.py 10000   # check a running entry from a client
mvn -f hybrid/pom.xml package test                            # the same build with Maven (CI)
```

Layout (Maven standard):

| Path | What it is |
|---|---|
| `pom.xml` | Maven build; Deephaven dependencies `provided`, JUnit 5 for tests |
| `build.py`, `run.py` | build without Maven (against the server's own jars); build and run with an entry point |
| `src/main/java/com/acme/hybrid/` | `Fast` (formula functions), `SignalFlipTracker` (Java listener plus `TablePublisher`), `HybridApp` (whole graph in Java) |
| `src/main/python/hybrid_py.py` | architecture A: the graph in Python, using the Java nodes |
| `src/main/resources/app.d/{python,java,groovy-console}/` | the application-mode entry points |
| `src/test/java/` | JUnit unit tests |
| `src/test/python/` | integration tests: `bench.py` (equivalence and timing), `check_entry.py` (both entries) |
| `results/bench.json` | the latest benchmark |

Measured, with identical results Python vs Java:

- **Per-row function:** 4.7–6.5x faster in Java.
- **Stateful listener:** 13–20x cheaper in Java, and it frees the GIL.

See GUIDE.md section 10 for the full numbers and what to move first.
