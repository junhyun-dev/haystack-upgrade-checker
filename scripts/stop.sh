#!/usr/bin/env bash
# Stop the Open WebUI process started by scripts/serve.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f runtime/openwebui.pid ]]; then
  PID="$(cat runtime/openwebui.pid)"
  if kill -0 "$PID" 2>/dev/null; then kill "$PID"; sleep 2; kill -9 "$PID" 2>/dev/null || true; fi
  rm -f runtime/openwebui.pid
  echo "stopped $PID"
else
  echo "not running"
fi
