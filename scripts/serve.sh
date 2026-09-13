#!/usr/bin/env bash
# Start Open WebUI v0.11.3 from the project venv on 127.0.0.1:8080 with config/openwebui.env.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p runtime/data runtime/cache runtime/logs
if [[ ! -f runtime/.webui_secret_key ]]; then
  python3 -c "import secrets; print(secrets.token_urlsafe(32))" > runtime/.webui_secret_key
  chmod 600 runtime/.webui_secret_key
fi
set -a; source config/openwebui.env; set +a
export WEBUI_SECRET_KEY="$(cat runtime/.webui_secret_key)"
if [[ -f runtime/openwebui.pid ]] && kill -0 "$(cat runtime/openwebui.pid)" 2>/dev/null; then
  echo "already running, pid $(cat runtime/openwebui.pid)"; exit 0
fi
nohup setsid .venv/bin/open-webui serve --host "$HOST" --port "$PORT" > runtime/logs/openwebui.log 2>&1 &
echo $! > runtime/openwebui.pid
echo "started pid $(cat runtime/openwebui.pid) -> http://$HOST:$PORT  (log: runtime/logs/openwebui.log)"
