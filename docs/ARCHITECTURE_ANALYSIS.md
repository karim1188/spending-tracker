# Architecture analysis: imessage-exporter → Spending Tracker

Inspected clone: `vendor/imessage-exporter` (GitHub `ReagentX/imessage-exporter`, default branch `develop`).

Upstream is **not** forked into the spending app. The exporter binary exports HTML/TXT archives. We only reuse the independently published **`imessage_database` library**.

## How the repository reads Messages

```
~/Library/Messages/chat.db
        │
        ▼
get_connection()          SQLITE_OPEN_READ_ONLY | SQLITE_OPEN_NO_MUTEX
        │
        ├── Handle::cache()     handle.ROWID → sender id (phone / short code / email)
        ├── Message::stream()   default full-table query
        └── Message::rows()     custom SQL (our incremental path)
                │
                ▼
        Message::parse_body()
                ├── attributedBody BLOB → crabstep TypedStreamDeserializer
                ├── fallback → streamtyped::parse() (plain text only)
                └── fallback → message.text column
                │
                ▼
        Message::date(offset)   Apple epoch 2001-01-01, ns or seconds
        Message::service()      iMessage | SMS | RCS | Satellite | Other
```

`get_connection` refuses missing paths and never opens the file for write. BLOB reads use `blob_open(..., read_only=true)`.

## Modules we can reuse

| Concern | Upstream location | Reuse |
|---|---|---|
| Open `chat.db` read-only | `imessage-database/src/tables/table.rs` → `get_connection` | Yes — do not reimplement |
| Message rows | `tables/messages/message.rs` → `Message` | Yes |
| Body / `attributedBody` | `Message::parse_body`, `tables/messages/body.rs`, `util/typedstream.rs`, `util/streamtyped.rs` | Yes — this is the hard part |
| Sender / handle | `tables/handle.rs` → `Handle::cache` | Yes |
| Timestamps | `util/dates.rs` → `get_offset`, `get_local_time`, `TIMESTAMP_FACTOR` | Yes |
| SMS vs iMessage | `tables/messages/models.rs` → `Service::from_name` | Yes |
| Default DB path | `util/dirs.rs` → `default_db_path` | Yes |
| HTML/TXT export | `imessage-exporter/` binary | **No** — wrong product |
| Attachments, tapbacks, balloons | message_types / exporters | Not needed for bank SMS |

`imessage_database` is a standalone crate (`crates.io` + workspace member). It does **not** require the exporter binary.

## Where message decoding happens

1. `Message::from_row` loads scalar columns. `text` is often `NULL` on modern macOS.
2. `Message::attributed_body(db)` reads the `attributedBody` BLOB.
3. `parse_body`:
   - Primary: `crabstep::TypedStreamDeserializer` → `parse_body_typedstream` (NSAttributedString object graph).
   - If that yields no text: `streamtyped::parse(body)` — byte scan for `[0x01, 0x2b]` … `[0x86, 0x84]`.
   - Finally: existing `message.text`.
4. `apply_body` writes decoded text back onto the struct.

Do **not** reimplement crabstep / typedstream in Python. Bank SMS is unstyled text, but modern Messages still stores it in `attributedBody`.

## Safest integration point

```
imessage_database (unmodified, path dep on vendor clone)
        ↓
thin Rust CLI  collector/imessage_reader
        ↓  JSON (rowid, guid, sender, text, timestamp, service, is_from_me)
Python IMessageReader adapter
        ↓
collector → bank filter → parsers → categorizer → spending.db
```

Why this boundary:

- Read-only guarantee stays in upstream `get_connection`.
- `attributedBody` stays in the proven Rust decoder.
- Spending schema never touches `chat.db`.
- Upstream can be updated by re-cloning; we do not patch it.
- Python tests use mock SQLite fixtures and never need a real Messages database.

Python also has a sqlite3 `mode=ro` reader for tests and for rows that still have `message.text`. If `text` is empty and the Rust helper is not built, the Python path uses a **faithful port of `streamtyped::parse` only** (plain-text fallback). It does not decode full typedstream attributes.

## What we will not do

- Modify Apple's `chat.db`.
- Store spending tables inside Messages.
- Turn `imessage-exporter` into this product.
- Call cloud / OpenAI / bank APIs.
- Invent bank sender IDs in `config/banks.json`.
