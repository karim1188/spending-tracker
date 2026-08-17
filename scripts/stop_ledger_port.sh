#!/usr/bin/env bash
# Back-compat wrapper — prefer scripts/stop_app.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/scripts/stop_app.sh" "${1:-8787}"
