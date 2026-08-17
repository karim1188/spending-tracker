#!/usr/bin/env bash
# Stop the Spending Tracker ledger (background deploy, Terminal, or caffeinate).
# Usage: bash scripts/stop_app.sh [port]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8787}"

echo "Stopping Spending Tracker (port $PORT)..."

collect_pids() {
  local found=""
  local pids

  pids="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    found="$found $pids"
  fi

  while IFS= read -r pid; do
    [ -n "$pid" ] && found="$found $pid"
  done < <(pgrep -f "$ROOT/scripts/start_app.py" 2>/dev/null || true)

  while IFS= read -r pid; do
    [ -n "$pid" ] && found="$found $pid"
  done < <(pgrep -f "caffeinate.*start_app.py" 2>/dev/null || true)

  echo "$found" | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u | tr '\n' ' '
}

stop_pids() {
  local signal="$1"
  local pids="$2"
  [ -z "${pids// /}" ] && return 0
  # shellcheck disable=SC2086
  kill $signal $pids 2>/dev/null || true
}

pids="$(collect_pids)"
if [ -z "${pids// /}" ]; then
  echo "Nothing running on port $PORT."
  exit 0
fi

echo "Found PID(s):$pids"
stop_pids "" "$pids"
sleep 2

remaining="$(collect_pids)"
if [ -n "${remaining// /}" ]; then
  echo "Force kill:$remaining"
  stop_pids "-9" "$remaining"
  sleep 1
fi

remaining="$(collect_pids)"
if [ -n "${remaining// /}" ]; then
  echo "[ERROR] Could not stop:$remaining"
  exit 1
fi

echo "Stopped. Port $PORT is free."
