from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.imessage_reader import IMessageReader, MessagesAccessError
from collector.logging_config import setup_logging
from collector.macos_access import FDA_HELP
from collector.message_collector import MessageCollector
from collector.project_paths import SPENDING_DB_PATH
from config.loader import BankRegistry
from database.db import SpendingDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one local Messages → spending sync")
    parser.add_argument("--db-path", type=Path, default=None, help="Path to chat.db (read-only)")
    parser.add_argument("--spending-db", type=Path, default=SPENDING_DB_PATH)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--reset-checkpoint", action="store_true")
    args = parser.parse_args()

    logger = setup_logging()
    reader = IMessageReader(db_path=args.db_path)
    access = reader.test_access()
    if not access.ok:
        print(access.message)
        return 2
    logger.info(access.message)

    with SpendingDatabase(args.spending_db) as db:
        collector = MessageCollector(db=db, reader=reader, registry=BankRegistry.load())
        if args.reset_checkpoint:
            collector.checkpoint.reset()
            logger.info("Checkpoint reset")
        try:
            stats = collector.sync_once(limit=args.limit)
        except MessagesAccessError as exc:
            print(str(exc))
            if exc.full_disk_access:
                print(FDA_HELP)
            return 2

    logger.info(
        "Sync complete: scanned=%s stored=%s ignored=%s duplicates=%s unknown=%s",
        stats.scanned,
        stats.stored,
        stats.ignored_non_bank,
        stats.skipped_duplicate,
        stats.unknown,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
