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
        description="Search Gmail on macOS via IMAP (Gmail only — not iCloud Mail)"
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
        help="Only messages on/after YYYY-MM-DD",
    )
    parser.add_argument(
        "--from",
        dest="from_pattern",
        default=None,
        help="Gmail search for this sender/text (e.g. thndr). Searches All Mail, not only INBOX.",
    )
    parser.add_argument(
        "--mailbox",
        default=None,
        help="IMAP mailbox. Default: [Gmail]/All Mail so archived mail is included.",
    )
    parser.add_argument(
        "--inbox",
        action="store_true",
        help="Stay on INBOX (skip All Mail)",
    )
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

    mailbox_arg = "INBOX" if args.inbox else (args.mailbox or cfg["mailbox"])
    reader = GmailReader(
        email=cfg["email"],
        app_password=cfg["app_password"],
        imap_host=cfg["imap_host"],
        mailbox=mailbox_arg,
    )

    if args.test:
        result = reader.test_access()
        if result.ok:
            logger.info(result.message)
            if result.unread_count is not None:
                logger.info("Unread in %s: %s", reader.mailbox, result.unread_count)
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

    query_used = ""
    try:
        with reader:
            if args.inbox:
                mailbox = reader.mailbox
            elif args.mailbox:
                reader.select_mailbox(args.mailbox)
                mailbox = reader.mailbox
            else:
                mailbox = reader.prefer_all_mail()

            if args.from_pattern:
                term = args.from_pattern.strip()
                queries = [f"from:{term}", f"subject:{term}", term]
                if args.unread:
                    queries = [f"is:unread {item}" for item in queries]
                query_used, uids = reader.search_gmail_uids(
                    queries,
                    since=since,
                    fallback_from=term,
                )
                if not uids:
                    messages = []
                else:
                    chosen = uids[-max(1, args.limit) :]
                    chosen.reverse()
                    messages = reader.peek_headers(chosen, full=True)
            else:
                query_used = "UNSEEN" if args.unread else "ALL"
                messages = reader.list_messages(
                    limit=max(1, args.limit),
                    unread_only=args.unread,
                    since=since,
                )
    except GmailConfigError as exc:
        print(str(exc))
        return 2

    label = "Unread Gmail" if args.unread else "Gmail search"
    print(label)
    print(f"Account: {mask_email(cfg['email'])} · mailbox: {mailbox}")
    if query_used:
        print(f"Query: {query_used}")
    print()
    if not messages:
        print("No matching messages.")
        if args.from_pattern and not args.inbox:
            print("Searched All Mail. If this is still empty, Thndr mail is not in this Gmail account.")
        elif args.from_pattern and args.inbox:
            print("INBOX only. Try without --inbox so archived mail in All Mail is included.")
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
