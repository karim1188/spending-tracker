# Local-first Spending Tracker

Read bank SMS from Apple Messages on a Mac, parse them on-device, and store structured transactions in a local SQLite database.

Nothing is uploaded. Apple's Messages database is opened **read-only**. There is no UI in this milestone.

## Clone on your Mac

```bash
git clone https://github.com/karim1188/spending-tracker.git
cd spending-tracker
chmod +x scripts/setup_macos.sh
./scripts/setup_macos.sh
```

If the repo is private, use SSH or `gh auth login` on the Mac first:

```bash
git clone git@github.com:karim1188/spending-tracker.git
cd spending-tracker
```

## Requirements

* macOS with Messages signed in
* iPhone **Text Message Forwarding** enabled so bank SMS appear on the Mac
  * iPhone: Settings → Messages → Text Message Forwarding → enable this Mac
* **Full Disk Access** for Terminal (or iTerm)
* Python 3.11+
* Rust (`rustup`) so the Messages helper can decode modern `attributedBody` blobs

## Make it work (Mac)

### 1. Full Disk Access

```text
System Settings
→ Privacy & Security
→ Full Disk Access
```

Enable **Terminal** (or iTerm). Quit and reopen the terminal after enabling.

Without this permission macOS refuses `~/Library/Messages/chat.db` even for a read-only open.

### 2. Install tools (if needed)

```bash
# Python
brew install python

# Rust (recommended)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

### 3. Install the app

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

Build the read-only Messages helper (uses the `imessage-database` crate, does not modify `chat.db`):

```bash
cd collector/imessage_reader
cargo build --release
cd ../..
```

Or run everything with:

```bash
./scripts/setup_macos.sh
source .venv/bin/activate
```

### 4. Prove Messages access

Always keep the venv active (`source .venv/bin/activate`).

```bash
python3 scripts/test_messages_access.py
```

Expected:

```text
OK — Messages database is readable and will not be modified.
```

If this fails, Full Disk Access is not granted to that terminal app.

### 5. Discover bank senders

```bash
python3 scripts/list_senders.py
```

Example:

```text
Incoming SMS senders

1. SNB                    145 messages
2. Amazon                  37 messages
3. +9665XXXXXXX            21 messages
```

Copy **only** confirmed bank short codes into `config/banks.json`. Do not invent sender IDs. Personal chats are ignored unless you add them.

```json
{
  "banks": {
    "SNB": { "senders": ["SNB"] },
    "AlRajhi": { "senders": [] },
    "RiyadBank": { "senders": [] },
    "SAB": { "senders": [] },
    "Alinma": { "senders": [] }
  }
}
```

If a bank uses a different SMS name (for example `AlAhli` instead of `SNB`), put that exact name in the matching `senders` list.

### 6. Import transactions

```bash
python3 scripts/sync_messages.py
python3 scripts/show_transactions.py
```

Watch for new SMS (CTRL+C to stop):

```bash
python3 scripts/watch_messages.py --interval 5
```

Reset the collector cursor if you change bank senders and want to rescan (duplicates are still blocked by message GUID):

```bash
python3 scripts/sync_messages.py --reset-checkpoint
```

## Privacy and safety

* `chat.db` is never modified, never copied into git, and never logged in full
* Only senders listed in `config/banks.json` are persisted
* Duplicate imports are blocked by unique `source_message_guid`
* No cloud APIs, OpenAI, bank APIs, or SMS forwarding services
* `database/spending.db` stays on this Mac and is gitignored

## Tests

```bash
source .venv/bin/activate
python3 -m pytest
```

Tests use mock SQLite fixtures. They do not open the real Messages database.

## Layout

```text
collector/          read-only Messages reader + incremental collector
parsers/            bank-specific parsers (SNB, AlRajhi, Riyad, SAB, Alinma)
categorizer/        local merchant rules
database/           spending SQLite schema (not chat.db)
config/banks.json   bank sender allow-list
scripts/            Mac commands
```

See `docs/ARCHITECTURE_ANALYSIS.md` for how `imessage-exporter` / `imessage_database` is reused.
