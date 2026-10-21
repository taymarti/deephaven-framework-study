"""
Run Deephaven Community as a plain Python process - no Docker.

Uses the `deephaven-server` pip package, which embeds the engine (a JVM) in
this Python process. Same server, same app.d scripts, same port as the
docker-compose setup, which stays available as an alternative.

Requirements: Java 17+ with JAVA_HOME set, and the packages in
requirements-server.txt. Linux, macOS and WSL 2 are the documented platforms
(server/setup_wsl.sh sets up WSL). Native Windows also works with two
workarounds this script applies automatically (verified on 42.6, Java 17):
  * the JVM's DLL folders are put on PATH, or the JVM crashes in jimage.dll;
  * web storage directories are made relative, or startup fails with
    "Invalid path: /layouts" (a leading slash resolves to the drive root).

  python server/run_server.py                      # anonymous auth, app.d scripts, port 10000
  python server/run_server.py --psk 's3cret'       # pre-shared-key auth instead
  python server/run_server.py --no-app             # empty server (console only)
  python -i server/run_server.py                   # same, plus a Python REPL in the server's scope
"""
from __future__ import annotations

import argparse
import os
import pathlib
import signal
import sys
import threading

HERE = pathlib.Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=10000)
    ap.add_argument("--heap", default="2g", help="JVM max heap, e.g. 2g")
    ap.add_argument("--psk", help="pre-shared key; omit for anonymous auth (localhost only!)")
    ap.add_argument("--app-dir", default=str(HERE / "app.d"), help="application-mode directory (*.app files)")
    ap.add_argument("--no-app", action="store_true", help="do not run application-mode scripts")
    ap.add_argument("--jvm-arg", action="append", default=[], help="extra JVM argument (repeatable)")
    args = ap.parse_args()

    if not os.environ.get("JAVA_HOME"):
        sys.exit("JAVA_HOME is not set; Deephaven needs Java 17+ (see server/setup_wsl.sh).")

    jvm_args = [f"-Xmx{args.heap}"]
    jvm_args.append(f"-Dauthentication.psk={args.psk}" if args.psk
                    else "-DAuthHandlers=io.deephaven.auth.AnonymousAuthenticationHandler")
    if not args.no_app:
        # Application mode: the same scripts the Docker image runs at boot.
        jvm_args.append(f"-Ddeephaven.application.dir={pathlib.Path(args.app_dir).resolve()}")
    jvm_args += args.jvm_arg
    if os.name == "nt":
        _windows_workarounds(jvm_args)

    # The Server must be created and started BEFORE anything imports `deephaven`.
    from deephaven_server import Server

    server = Server(port=args.port, jvm_args=jvm_args)
    server.start()
    print(f"\nDeephaven is up:  http://localhost:{args.port}/ide/"
          f"   ({'PSK' if args.psk else 'anonymous'} auth, app.d {'off' if args.no_app else 'on'})", flush=True)

    if sys.flags.interactive:
        return  # `python -i`: drop into a REPL; the server lives as long as the process
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    print("Ctrl+C to stop.", flush=True)
    stop.wait()


def _windows_workarounds(jvm_args: list) -> None:
    java_home = pathlib.Path(os.environ["JAVA_HOME"])
    dll_dirs = [java_home / "bin", java_home / "bin" / "server"]
    os.environ["PATH"] = os.pathsep.join([str(d) for d in dll_dirs] + [os.environ.get("PATH", "")])
    for d in dll_dirs:
        if d.is_dir():
            os.add_dll_directory(str(d))
    for prop, value in (("web.storage.layout.directory", "layouts"),
                        ("web.storage.notebook.directory", "notebooks")):
        if not any(a.startswith(f"-D{prop}=") for a in jvm_args):
            jvm_args.append(f"-D{prop}={value}")


if __name__ == "__main__":
    main()
