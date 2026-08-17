#!/usr/bin/env bash
# Stop whatever is listening on the ledger port (default 8787).
set -euo pipefail
PORT="${1:-8787}"
pids=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)
if [ -z "$pids" ]; then
  echo "Port $PORT is free."
  exit 0
fi
echo "Stopping PID(s) on port $PORT: $pids"
# shellcheck disable=SC2086
kill $pids 2>/dev/null || true
sleep 2
pids=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)
if [ -n "$pids" ]; then
  echo "Force kill: $pids"
  # shellcheck disable=SC2086
  kill -9 $pids 2>/dev/null || true
fi
echo "Done."
