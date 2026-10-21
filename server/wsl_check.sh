#!/usr/bin/env bash
# Read-only readiness check for running the pip Deephaven server in WSL.
. /etc/os-release; echo "distro: $PRETTY_NAME"
echo "python: $(python3 --version 2>&1)"
python3 -c 'import venv, ensurepip' 2>/dev/null && echo "venv: ok" || echo "venv: missing (python3-venv)"
if command -v java >/dev/null; then echo "java: $(java -version 2>&1 | head -1)"; else echo "java: none"; fi
echo "JAVA_HOME=${JAVA_HOME:-<unset>}"
echo "disk free in ~: $(df -h ~ | awk 'NR==2{print $4}')"
sudo -n true 2>/dev/null && echo "sudo without password: yes" || echo "sudo without password: no"
echo "arch: $(uname -m)"
