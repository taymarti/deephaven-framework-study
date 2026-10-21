#!/usr/bin/env bash
# Start the embedded Deephaven server (after setup_wsl.sh). Extra args go to run_server.py.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${DH_VENV:-$HOME/.venvs/deephaven-compare}"
export JAVA_HOME="${JAVA_HOME:-$(cat "$VENV/.java_home")}"
exec "$VENV/bin/python" "$HERE/run_server.py" "$@"
