#!/usr/bin/env bash
# 업그레이드 점검 도우미 (app/main.py) on 127.0.0.1:8090 — own port, localhost only. Usage: start|start-verify|stop|status
# start-verify: VERIFY_MODE=1 — the app refuses model server start, inference and Open WebUI calls (for screen checks).
# The log is appended, not truncated, so a previous instance's record survives a restart.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
PIDF="runtime/app.pid"; LOG="runtime/logs/app.log"
mkdir -p runtime/logs runtime/eval/runs  # a fresh checkout has no runtime/ yet
# Is the process in app.pid really this port's app, and in verify mode? Three bindings, all read-only:
#   the PID's own environment (VERIFY_MODE=1), the PID listening on 8090, and the app on 8090 reporting verify_mode true.
# Prints one of: verified | normal-mode | unconfirmed:<why>. Never stops or restarts anything.
confirm_verify() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || { echo "unconfirmed:pid $pid not alive"; return; }
  local env; env=$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null) || { echo "unconfirmed:cannot read environment of pid $pid"; return; }
  if ! grep -qx 'VERIFY_MODE=1' <<< "$env"; then echo "normal-mode"; return; fi
  ss -ltnp 2>/dev/null | grep -q "127.0.0.1:8090 .*pid=$pid," || { echo "unconfirmed:pid $pid is not the listener on 8090"; return; }
  local h; h=$(curl -s -m 5 http://127.0.0.1:8090/health 2>/dev/null) || { echo "unconfirmed:no /health answer"; return; }
  grep -q '"verify_mode":true' <<< "$h" || { echo "unconfirmed:/health says $h"; return; }
  echo "verified"
}
case "${1:-status}" in
  start|start-verify)
    if [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
      PID=$(cat "$PIDF")
      if [[ "$1" == "start-verify" ]]; then
        R=$(confirm_verify "$PID")
        case "$R" in
          verified) echo "already running pid $PID — verify mode confirmed (environment, listener, /health)"; exit 0;;
          normal-mode) echo "already running pid $PID in NORMAL mode — not verify mode. Not stopping it; stop it yourself and run start-verify" >&2; exit 2;;
          *) echo "already running pid $PID — verify mode NOT confirmed (${R#unconfirmed:})" >&2; exit 3;;
        esac
      fi
      echo "already running pid $PID"; exit 0
    fi
    MODE=0; [[ "$1" == "start-verify" ]] && MODE=1
    echo "=== $(date '+%F %T') start (VERIFY_MODE=$MODE) ===" >> "$LOG"
    VERIFY_MODE=$MODE nohup setsid .venv-app/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090 >> "$LOG" 2>&1 &
    echo $! > "$PIDF"; PID=$(cat "$PIDF")
    echo "launched pid $PID (VERIFY_MODE=$MODE) -> http://127.0.0.1:8090 (log: $LOG)"
    if [[ "$MODE" == 1 ]]; then   # launching is not the same as the mode being in effect: confirm before reporting ready
      R=unconfirmed:not-yet
      for _ in $(seq 1 30); do R=$(confirm_verify "$PID"); [[ "$R" == verified || "$R" == normal-mode ]] && break; sleep 0.5; done
      case "$R" in
        verified) echo "verify mode confirmed for pid $PID (environment, listener, /health)"; exit 0;;
        *) echo "verify mode NOT confirmed for pid $PID (${R#unconfirmed:}) — do not use this instance for checks" >&2; exit 3;;
      esac
    fi;;
  stop) if [[ -f "$PIDF" ]]; then kill "$(cat "$PIDF")" 2>/dev/null || true; rm -f "$PIDF"; echo stopped; else echo "not running"; fi;;
  status) if [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then ps -o pid,rss,etime -p "$(cat "$PIDF")" | tail -1; curl -s -m 5 http://127.0.0.1:8090/health; echo; else echo "not running"; fi;;
esac
