#!/usr/bin/env bash
# One-time: enable `git deploy-push` = push to GitHub + restart Mac ledger.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
chmod +x "$ROOT/scripts/restart_after_pull.sh" 2>/dev/null || true
git config alias.deploy-push "!python3 '$ROOT/scripts/push_and_deploy.py'"
echo "Installed git alias: git deploy-push"
echo "Use instead of git push when you want the Mac to pull and restart:"
echo "  git deploy-push"
