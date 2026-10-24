"""
Build the Java half of the project (src/main/java) into target/hybrid.jar,
compiled against the exact Deephaven jars the server runs (the deephaven-server
pip package), so there is no version skew and no Maven download. The same
sources build with `mvn package` (pom.xml) in CI.

    python hybrid/build.py            # incremental: rebuilds only when a .java is newer than the jar
    python hybrid/build.py --clean

Needs a JDK (javac) in JAVA_HOME. Unit tests (src/test/java, JUnit 5) run with
`mvn test`; this script builds main sources only.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "src" / "main" / "java"
OUT = HERE / "target"      # Maven's output folder
JAR = OUT / "hybrid.jar"


def deephaven_jars() -> pathlib.Path:
    import importlib.util
    spec = importlib.util.find_spec("deephaven_server")
    if spec is None:
        sys.exit("deephaven_server is not installed in this Python (use the server venv)")
    return pathlib.Path(spec.origin).parent / "jars"


def build(clean: bool = False) -> pathlib.Path:
    sources = sorted(SRC.rglob("*.java"))
    if clean and OUT.exists():
        shutil.rmtree(OUT)
    if JAR.exists() and all(s.stat().st_mtime <= JAR.stat().st_mtime for s in sources):
        print(f"up to date: {JAR}")
        return JAR
    javac = pathlib.Path(os.environ["JAVA_HOME"]) / "bin" / ("javac.exe" if os.name == "nt" else "javac")
    classes = OUT / "classes"
    shutil.rmtree(classes, ignore_errors=True)
    classes.mkdir(parents=True)
    cp = str(deephaven_jars() / "*")
    subprocess.run([str(javac), "--release", "17", "-encoding", "UTF-8", "-cp", cp, "-d", str(classes),
                    *map(str, sources)], check=True)
    with zipfile.ZipFile(JAR, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(classes.rglob("*.class")):
            z.write(f, f.relative_to(classes).as_posix())
    print(f"built {JAR} from {len(sources)} sources")
    return JAR


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true")
    build(ap.parse_args().clean)
