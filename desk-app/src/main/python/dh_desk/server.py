"""
`dh-desk-server`: start Deephaven in this process with the bundled Java jar on the classpath,
build the app, and publish its tables.

    dh-desk-server                    # http://localhost:10000/ide/ , ops dashboard at /iframe/widget/?name=desk_ops
    dh-desk-server --port 10000 --heap 4g
    dh-desk-server --psk s3cret       # pre-shared-key auth instead of anonymous (localhost only!)

Needs a Java 17+ JDK in JAVA_HOME (the engine compiles formulas at runtime, so a JRE is not enough).
"""
import argparse
import logging
import os
import pathlib
import signal
import sys
import threading


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="dh-desk-server", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=10000)
    ap.add_argument("--heap", default="2g")
    ap.add_argument("--psk", help="pre-shared key; omit for anonymous auth")
    ap.add_argument("--jvm-arg", action="append", default=[])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not os.environ.get("JAVA_HOME"):
        sys.exit("dh-desk-server: set JAVA_HOME to a Java 17+ JDK")
    from dh_desk.resources import java_jar
    jvm_args = [f"-Xmx{args.heap}", (f"-Dauthentication.psk={args.psk}" if args.psk
                                     else "-DAuthHandlers=io.deephaven.auth.AnonymousAuthenticationHandler"),
                *args.jvm_arg]
    if os.name == "nt":
        _windows_workarounds(jvm_args)

    from deephaven_server import Server  # must start before anything imports `deephaven`
    Server(port=args.port, jvm_args=jvm_args, extra_classpath=[str(java_jar())]).start()

    # This thread started the server, so it holds the real execution context: build here.
    from dh_desk import app
    published = app.build()
    import __main__  # with the pip server, the launcher's __main__ is the console scope
    for name, obj in published.items():
        setattr(__main__, name, obj)

    print(f"\ndh-desk is up: http://localhost:{args.port}/ide/   "
          f"ops dashboard: http://localhost:{args.port}/iframe/widget/?name=desk_ops\n"
          f"tables: {', '.join(n for n in published if not n.startswith('_'))}\n"
          f"trader UI: run `dh-desk-web --dh-url http://localhost:{args.port}`", flush=True)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()


def _windows_workarounds(jvm_args: list) -> None:
    """Native Windows (verified on 42.6, Java 17): the JVM's DLL folders must be on PATH, and web
    storage directories must be relative, or the server fails to start."""
    jh = pathlib.Path(os.environ["JAVA_HOME"])
    dll_dirs = [jh / "bin", jh / "bin" / "server"]
    os.environ["PATH"] = os.pathsep.join([str(d) for d in dll_dirs] + [os.environ.get("PATH", "")])
    for d in dll_dirs:
        if d.is_dir():
            os.add_dll_directory(str(d))
    jvm_args += ["-Dweb.storage.layout.directory=layouts", "-Dweb.storage.notebook.directory=notebooks"]


if __name__ == "__main__":
    main()
