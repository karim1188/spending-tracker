#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Spending Tracker macOS setup"
echo "    Project: $ROOT"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/ or: brew install python"
  exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"

if command -v cargo >/dev/null 2>&1; then
  echo "==> Building read-only Messages helper (imessage_database)"
  (cd collector/imessage_reader && cargo build --release)
else
  echo "==> cargo not found. Install Rust for reliable attributedBody decoding:"
  echo "    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  echo "    then reopen Terminal and re-run this script."
fi

echo
echo "==> Testing Messages access (read-only)"
python3 scripts/test_messages_access.py || true

echo
echo "Next:"
echo "  1. Grant Full Disk Access to Terminal (or iTerm) if the test failed"
echo "  2. source .venv/bin/activate"
echo "  3. python3 scripts/list_senders.py"
echo "  4. Add bank short codes to config/banks.json"
echo "  5. python3 scripts/sync_messages.py"
