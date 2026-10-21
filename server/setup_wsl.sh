#!/usr/bin/env bash
# One-time setup for server/run_server.py inside WSL 2 (or any Linux).
#   bash server/setup_wsl.sh        then        bash server/start.sh
# Java 17+ must already be installed, e.g.:  sudo apt install -y openjdk-21-jre-headless
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${DH_VENV:-$HOME/.venvs/deephaven-compare}"   # Linux filesystem: much faster than /mnt/c

# Find a Java 17+ home: $JAVA_HOME, then the usual apt locations.
pick_java() {
  for j in "${JAVA_HOME:-}" /usr/lib/jvm/java-21-openjdk-amd64 /usr/lib/jvm/java-17-openjdk-amd64 /usr/lib/jvm/*; do
    [ -n "$j" ] && [ -x "$j/bin/java" ] || continue
    v=$("$j/bin/java" -version 2>&1 | awk -F'"' '/version/{split($2,a,"."); print a[1]}')
    [ "${v:-0}" -ge 17 ] && { echo "$j"; return; }
  done
}
JH="$(pick_java || true)"
if [ -z "$JH" ]; then
  echo "No Java 17+ found. Install one, e.g.:  sudo apt install -y openjdk-21-jre-headless" >&2
  exit 1
fi
echo "Java: $JH"

python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip setuptools wheel
"$VENV/bin/pip" install -q -r "$HERE/requirements-server.txt"
echo "$JH" > "$VENV/.java_home"
echo "Ready. Start with:  bash $HERE/start.sh   (venv: $VENV)"
command -v dot >/dev/null || echo "Optional: sudo apt install -y graphviz  (SVG update-graph pictures)"
