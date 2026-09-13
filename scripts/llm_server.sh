#!/usr/bin/env bash
# Local CPU LLM server (llama.cpp llama-server, MIT) serving Qwen3-4B-Q4_K_M (Apache-2.0) on 127.0.0.1:8081, OpenAI-compatible.
# Usage: scripts/llm_server.sh start|stop|status|window-open <consumer>|window-close <consumer>
# A window serializes use by local consumers. While a window lock exists,
# the assistant app does not stop the server or start another check.
# This optional script is not needed by the synthetic verification demo.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
BIN="runtime/llama.cpp/llama-server"; MODEL="runtime/models/Qwen3-4B-Q4_K_M.gguf"; PIDF="runtime/llama-server.pid"; LOG="runtime/logs/llama-server.log"
CTX="${LLM_CTX:-4096}"; THREADS="${LLM_THREADS:-6}"
case "${1:-status}" in
  start)
    if [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then echo "already running pid $(cat "$PIDF")"; exit 0; fi
    [[ -x "$BIN" && -f "$MODEL" ]] || { echo "missing $BIN or $MODEL (run scripts/fetch_models.sh)"; exit 1; }
    export LD_LIBRARY_PATH="$ROOT/runtime/llama.cpp:${LD_LIBRARY_PATH:-}"
    nohup setsid "$BIN" -m "$MODEL" --host 127.0.0.1 --port 8081 -c "$CTX" -t "$THREADS" --alias qwen3-4b -np 1 \
      --reasoning-format deepseek > "$LOG" 2>&1 &
    echo $! > "$PIDF"; echo "started pid $(cat "$PIDF") -> http://127.0.0.1:8081/v1 (log: $LOG)";;
  stop)
    if [[ -f "$PIDF" ]]; then kill "$(cat "$PIDF")" 2>/dev/null || true; rm -f "$PIDF"; echo stopped; else echo "not running"; fi;;
  status)
    if [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then ps -o pid,rss,etime -p "$(cat "$PIDF")" | tail -1; curl -s -m 5 http://127.0.0.1:8081/health; echo; else echo "not running"; fi
    [[ -f runtime/llm_window.lock ]] && echo "window open: $(cat runtime/llm_window.lock)" || true;;
  window-open)
    CONSUMER="${2:?consumer name required}"
    if [[ -f runtime/llm_window.lock ]]; then echo "window already open: $(cat runtime/llm_window.lock)"; exit 2; fi
    "$0" start; printf '%s %s ctx=%s threads=%s\n' "$CONSUMER" "$(date -Is)" "$CTX" "$THREADS" > runtime/llm_window.lock
    for i in $(seq 1 60); do curl -s -m 3 http://127.0.0.1:8081/health 2>/dev/null | grep -q ok && break; sleep 2; done
    echo "on: $(cat runtime/llm_window.lock)";;
  window-close)
    CONSUMER="${2:?consumer name required}"
    if [[ -f runtime/llm_window.lock ]] && ! grep -q "^$CONSUMER " runtime/llm_window.lock; then echo "window belongs to: $(cat runtime/llm_window.lock)"; exit 2; fi
    rm -f runtime/llm_window.lock; "$0" stop
    for i in $(seq 1 20); do pgrep -f "runtime/llama.cpp/llama-server" >/dev/null || break; sleep 1; done
    if pgrep -f "runtime/llama.cpp/llama-server" >/dev/null; then pkill -9 -f "runtime/llama.cpp/llama-server" || true; sleep 1; fi
    if pgrep -f "runtime/llama.cpp/llama-server" >/dev/null; then echo "WARNING: llama-server still running"; exit 1; fi
    echo "done: window closed, llama-server stopped, available memory $(free -m | awk 'NR==2{print $7}')MB";;
esac
