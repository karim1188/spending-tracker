#!/usr/bin/env bash
# Detached worker: wait for the ledger to stop, git pull, start again.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${DEPLOY_PORT:-8787}"
BRANCH="${DEPLOY_BRANCH:-main}"
LOG="$ROOT/logs/deploy.log"
START_CMD="${DEPLOY_START_COMMAND:-}"

if [ -z "$START_CMD" ]; then
  if [ -x "$ROOT/.venv/bin/python3" ]; then
    START_CMD="$ROOT/.venv/bin/python3 scripts/start_app.py --no-browser"
  else
    START_CMD="python3 scripts/start_app.py --no-browser"
  fi
fi

log() {
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*" | tee -a "$LOG"
}

port_pids() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | tr '\n' ' ' || true
}

stop_port_listeners() {
  local pids
  pids="$(port_pids)"
  if [ -z "${pids// /}" ]; then
    return 0
  fi
  log "Stopping listener(s) on port $PORT: $pids"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 2
  pids="$(port_pids)"
  if [ -n "${pids// /}" ]; then
    log "Force-killing listener(s) on port $PORT: $pids"
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi
}

log "Deploy worker started (branch=$BRANCH port=$PORT)"

# Wait for the API server to shut down after deploy (up to 90s).
for _ in $(seq 1 90); do
  if [ -z "$(port_pids)" ]; then
    break
  fi
  sleep 1
done

stop_port_listeners

if [ -n "$(port_pids)" ]; then
  log "ERROR: port $PORT still in use after 90s"
  exit 1
fi

log "git pull origin $BRANCH"
if ! git pull --ff-only origin "$BRANCH" >>"$LOG" 2>&1; then
  log "WARN: fast-forward pull failed; trying regular git pull"
  git pull origin "$BRANCH" >>"$LOG" 2>&1
fi

# Port can be grabbed again during pull; clear before bind.
stop_port_listeners

log "Starting app: $START_CMD"
nohup bash -lc "cd '$ROOT' && $START_CMD" >>"$LOG" 2>&1 &
new_pid=$!
log "Started PID $new_pid"

for _ in $(seq 1 20); do
  if [ -n "$(port_pids)" ]; then
    log "Ledger listening on port $PORT"
    exit 0
  fi
  if ! kill -0 "$new_pid" 2>/dev/null; then
    log "ERROR: app exited before binding port $PORT (see $LOG)"
    exit 1
  fi
  sleep 1
done

log "WARN: app PID $new_pid running but port $PORT not listening yet"
