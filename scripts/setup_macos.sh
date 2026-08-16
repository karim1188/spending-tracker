#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Spending Tracker macOS setup"
echo "    Project: $ROOT"
echo

pick_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    echo python3
    return 0
  fi
  return 1
}

if ! PYTHON_BIN="$(pick_python)"; then
  echo "Python 3.11+ is required."
  echo
  echo "Upgrade on this Mac:"
  echo "  brew install python@3.12"
  echo "  echo 'export PATH=\"\$(brew --prefix python@3.12)/libexec/bin:\$PATH\"' >> ~/.zprofile"
  echo "  source ~/.zprofile"
  echo
  echo "Then delete the old venv and re-run this script:"
  echo "  rm -rf .venv venv"
  echo "  ./scripts/setup_macos.sh"
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[0])')"
PY_MINOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[1])')"

echo "    Using: $PYTHON_BIN ($PY_VERSION)"

if [ "$PY_MAJOR" -lt 3 ] || [ "$PY_MINOR" -lt 11 ]; then
  echo
  echo "This Mac is using Python $PY_VERSION. The app needs 3.11 or newer."
  echo "Do not keep using the system /usr/bin/python3 (often 3.9)."
  echo
  echo "Upgrade with Homebrew:"
  echo "  brew install python@3.12"
  echo "  rm -rf .venv venv"
  echo "  \$(brew --prefix python@3.12)/bin/python3.12 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  python3 --version"
  echo "  ./scripts/setup_macos.sh"
  echo
  echo "Or install from https://www.python.org/downloads/macos/ (3.12 or 3.13)."
  exit 1
fi

"$PYTHON_BIN" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"

if command -v cargo >/dev/null 2>&1; then
  echo "==> Building read-only Messages helper (imessage_database)"
  (cd collector/imessage_reader && cargo build --release)
else
  echo "==> cargo not found. Install Rust for reliable attributedBody decoding:"
  echo "    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  echo "    then reopen Terminal and run: source \"\$HOME/.cargo/env\""
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
