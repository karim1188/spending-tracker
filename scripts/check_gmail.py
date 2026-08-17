from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.gmail_reader import GmailConfigError, GmailReader, load_gmail_config, mask_email
from collector.logging_config import setup_logging
from collector.project_paths import GMAIL_CONFIG_PATH, GMAIL_EXAMPLE_PATH


def _format_when(when: datetime | None) -> str:
    if when is None:
        return "unknown date"
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Gmail inbox on macOS via IMAP (Gmail only — not iCloud Mail)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=GMAIL_CONFIG_PATH,
        help=f"Gmail config JSON (default: {GMAIL_CONFIG_PATH})",
    )
    parser.add_argument("--test", action="store_true", help="Test Gmail IMAP login only")
    parser.add_argument("--limit", type=int, default=15, help="Max messages to list")
    parser.add_argument("--unread", action="store_true", help="Unread messages only")
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only messages on/after YYYY-MM-DD (IMAP SINCE)",
    )
    parser.add_argument("--from", dest="from_pattern", default=None, help="Filter sender text")
    args = parser.parse_args()
    logger = setup_logging()

    try:
        cfg = load_gmail_config(args.config)
    except GmailConfigError as exc:
        print(str(exc))
        print(f"Example config: {GMAIL_EXAMPLE_PATH}")
        print("Gmail → Settings → Forwarding and POP/IMAP → Enable IMAP")
        print("Google Account → Security → App passwords → generate one for Mail")
        return 2

    reader = GmailReader(
        email=cfg["email"],
        app_password=cfg["app_password"],
        imap_host=cfg["imap_host"],
        mailbox=cfg["mailbox"],
    )

    if args.test:
        result = reader.test_access()
        if result.ok:
            logger.info(result.message)
            if result.unread_count is not None:
                logger.info("Unread in %s: %s", cfg["mailbox"], result.unread_count)
            print(f"OK — Gmail reachable for {mask_email(result.email or cfg['email'])}")
            if result.unread_count is not None:
                print(f"Unread: {result.unread_count}")
            return 0
        print(result.message)
        return 2

    since = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print("Invalid --since date; use YYYY-MM-DD")
            return 2

    try:
        with reader:
            messages = reader.list_messages(
                limit=max(1, args.limit),
                unread_only=args.unread,
                since=since,
                from_pattern=args.from_pattern,
            )
    except GmailConfigError as exc:
        print(str(exc))
        return 2

    label = "Unread Gmail" if args.unread else "Recent Gmail"
    print(label)
    print(f"Account: {mask_email(cfg['email'])} · mailbox: {cfg['mailbox']}")
    print()
    if not messages:
        print("No matching messages.")
        return 0

    for index, msg in enumerate(messages, start=1):
        unread = "unread" if msg.unread else "read"
        print(f"{index}. [{unread}] {_format_when(msg.date)}")
        print(f"   From: {mask_email(msg.from_addr)}")
        print(f"   Subject: {msg.subject}")
        if msg.snippet:
            print(f"   Snippet: {msg.snippet[:160]}")
        print()

    print(f"Listed {len(messages)} message(s). Read-only — nothing was marked read or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
