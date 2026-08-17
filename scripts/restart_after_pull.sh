#!/usr/bin/env bash
# Detached worker: wait for the ledger to stop, git pull, start again.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${DEPLOY_PORT:-8787}"
BRANCH="${DEPLOY_BRANCH:-main}"
LOG="$ROOT/logs/deploy.log"
START_CMD="${DEPLOY_START_COMMAND:-python3 scripts/start_app.py --no-browser}"

log() {
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*" | tee -a "$LOG"
}

log "Deploy worker started (branch=$BRANCH port=$PORT)"

for _ in $(seq 1 45); do
  if ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  log "ERROR: port $PORT still in use after 45s"
  exit 1
fi

log "git pull origin $BRANCH"
if ! git pull --ff-only origin "$BRANCH" >>"$LOG" 2>&1; then
  log "WARN: fast-forward pull failed; trying regular git pull"
  git pull origin "$BRANCH" >>"$LOG" 2>&1
fi

log "Starting app: $START_CMD"
nohup bash -lc "cd '$ROOT' && $START_CMD" >>"$LOG" 2>&1 &
log "Started PID $!"
