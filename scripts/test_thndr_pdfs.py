from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.gmail_reader import (
    GmailConfigError,
    GmailReader,
    load_gmail_config,
    mask_email,
)
from collector.logging_config import setup_logging
from collector.project_paths import GMAIL_CONFIG_PATH, GMAIL_EXAMPLE_PATH, LOGS_DIR
from collector.thndr_pdf import (
    THNDR_GMAIL_QUERIES,
    InvoiceTrade,
    PdfParseResult,
    aggregate_stocks,
    is_skip_filename,
    parse_pdf_bytes,
    parse_pdf_file,
)


def _format_when(when: datetime | None) -> str:
    if when is None:
        return "unknown date"
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _print_parse_result(result: PdfParseResult) -> list[InvoiceTrade]:
    date_label = result.date.isoformat() if result.date else "no date"
    print(f"{result.filename}: {result.kind} ({date_label})")
    if result.error:
        print(f"  error: {result.error}")
    elif result.kind == "statement":
        print("  statement is archived by the portfolio app; quantities come from invoices")
        if result.preview:
            print(f"  preview: {result.preview[:160]}")
    elif result.kind == "other":
        print("  unrecognized PDF (portfolio would keep a sample)")
    elif result.kind == "skipped":
        print("  skipped (contract/agreement)")
    for trade in result.trades:
        print(
            f"  {trade.type} {trade.quantity} {trade.symbol or trade.ticker} "
            f"@ {trade.price} {trade.currency}  {trade.isin}"
        )
    print()
    return list(result.trades)


def _print_trades(trades: list[InvoiceTrade]) -> None:
    if not trades:
        print("No invoice trades parsed.")
        return
    print("Invoice trades (what the portfolio would store as transactions)")
    print()
    for trade in trades:
        print(
            f"  {trade.date}  {trade.type:<4}  {trade.quantity:>8}  "
            f"{trade.symbol or trade.ticker:<12}  {trade.isin}  "
            f"{trade.price:.4f} {trade.currency}  {trade.name}"
        )
    print()
    print("Stocks that would be created/updated (net qty from these invoices)")
    print()
    for stock in aggregate_stocks(trades):
        print(
            f"  {stock['symbol']:<12}  {stock['isin']:<16}  "
            f"qty {stock['quantity']:>8}  {stock['market']:<4}  "
            f"{stock['currency']}  {stock['name']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Test Thndr PDF → stock parsing on the Mac. "
            "Uses Gmail IMAP (same config as scripts/check_gmail.py). "
            "Does not write the portfolio database."
        )
    )
    parser.add_argument("--config", type=Path, default=GMAIL_CONFIG_PATH)
    parser.add_argument("--limit", type=int, default=8, help="Max Thndr emails or local PDFs")
    parser.add_argument("--since", type=str, default=None, help="Only emails on/after YYYY-MM-DD")
    parser.add_argument(
        "--from-dir",
        type=Path,
        default=None,
        help="Parse PDFs from a local folder instead of Gmail",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=LOGS_DIR / "thndr_pdfs",
        help="Where to write downloaded PDFs (ignored with --no-save)",
    )
    parser.add_argument("--no-save", action="store_true", help="Parse in memory, do not write PDFs")
    parser.add_argument(
        "--mailbox",
        default=None,
        help='IMAP mailbox (default: Gmail All Mail, then config mailbox/INBOX)',
    )
    args = parser.parse_args()
    setup_logging()

    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        print("pdfplumber is required to read Thndr PDFs.")
        print('Install with: python3 -m pip install "pdfplumber>=0.11"')
        return 2

    all_trades: list[InvoiceTrade] = []

    if args.from_dir is not None:
        folder = args.from_dir.expanduser()
        if not folder.is_dir():
            print(f"Folder not found: {folder}")
            return 2
        pdf_paths = sorted(path for path in folder.iterdir() if path.suffix.lower() == ".pdf")
        pdf_paths = pdf_paths[-max(1, args.limit) :]
        print(f"Parsing {len(pdf_paths)} PDF(s) from {folder}")
        print()
        for path in pdf_paths:
            all_trades.extend(_print_parse_result(parse_pdf_file(path)))
        _print_trades(all_trades)
        return 0

    try:
        cfg = load_gmail_config(args.config)
    except GmailConfigError as exc:
        print(str(exc))
        print(f"Example config: {GMAIL_EXAMPLE_PATH}")
        return 2

    since = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print("Invalid --since date; use YYYY-MM-DD")
            return 2

    reader = GmailReader(
        email=cfg["email"],
        app_password=cfg["app_password"],
        imap_host=cfg["imap_host"],
        mailbox=args.mailbox or cfg["mailbox"],
    )
    print(f"Searching Gmail for Thndr PDFs ({mask_email(cfg['email'])})")
    print()
    try:
        with reader:
            if args.mailbox:
                reader.select_mailbox(args.mailbox)
                mailbox = reader.mailbox
            else:
                mailbox = reader.prefer_all_mail()
            query, uids = reader.search_gmail_uids(
                THNDR_GMAIL_QUERIES,
                since=since,
                fallback_from="thndr.app",
            )
            print(f"Mailbox: {mailbox}")
            print(f"Query: {query or '(none matched)'}")
            print(f"Matched {len(uids)} message(s)")
            print()
            if not uids:
                print("No Thndr emails found in this mailbox.")
                print("If they exist in Gmail, they may be in another account than config/gmail.json.")
                return 0
            chosen = uids[-max(1, args.limit) :]
            chosen.reverse()
            headers = reader.peek_headers(chosen)
            print("Matching emails")
            for msg in headers:
                print(f"  {_format_when(msg.date)}  {msg.subject}")
                print(f"     From: {mask_email(msg.from_addr)}")
            print()
            attachments = reader.fetch_pdf_attachments(chosen)
    except GmailConfigError as exc:
        print(str(exc))
        return 2
    except Exception as exc:
        print(f"Gmail fetch failed: {exc}")
        return 2

    if not attachments:
        print("Those emails had no PDF attachments (or the PDF part could not be decoded).")
        return 0

    print(f"Found {len(attachments)} PDF attachment(s) (read-only, not marked read)")
    saved = 0
    for attachment in attachments:
        print(f"  {_format_when(attachment.date)}  {attachment.subject}")
        print(f"     file: {attachment.filename}  ({len(attachment.data)} bytes)")
        result = parse_pdf_bytes(attachment.data, filename=attachment.filename)
        all_trades.extend(_print_parse_result(result))
        if not args.no_save and not is_skip_filename(attachment.filename):
            args.save_dir.mkdir(parents=True, exist_ok=True)
            safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in attachment.filename)[:80]
            dest = args.save_dir / f"{attachment.uid}_{safe or 'attachment.pdf'}"
            dest.write_bytes(attachment.data)
            saved += 1

    if saved:
        print(f"Saved {saved} PDF(s) to {args.save_dir}")
        print()

    _print_trades(all_trades)
    print()
    print("Read-only Gmail access. Nothing was marked read, deleted, or written to a portfolio DB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
