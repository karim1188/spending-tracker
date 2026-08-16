from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.imessage_reader import IMessageReader, MessagesAccessError
from collector.logging_config import setup_logging
from collector.message_collector import MessageCollector
from collector.project_paths import SPENDING_DB_PATH
from config.loader import BankRegistry
from database.db import SpendingDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch Messages locally and import bank SMS")
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--spending-db", type=Path, default=SPENDING_DB_PATH)
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between checks")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    logger = setup_logging()
    running = True

    def _stop(signum, _frame):
        nonlocal running
        running = False
        logger.info("Shutting down watcher (signal %s)", signum)

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    reader = IMessageReader(db_path=args.db_path)
    access = reader.test_access()
    if not access.ok:
        print(access.message)
        return 2
    logger.info(access.message)
    logger.info("Watcher interval: %s seconds", args.interval)

    with SpendingDatabase(args.spending_db) as db:
        collector = MessageCollector(db=db, reader=reader, registry=BankRegistry.load())
        while running:
            try:
                stats = collector.sync_once(limit=args.limit)
                if stats.scanned:
                    logger.info(
                        "Cycle stored=%s ignored=%s",
                        stats.stored,
                        stats.ignored_non_bank,
                    )
            except MessagesAccessError as exc:
                logger.info("Read failed: %s", exc)
            except Exception as exc:  # noqa: BLE001 — keep watcher alive
                logger.info("Cycle error: %s", exc)
            slept = 0.0
            while running and slept < args.interval:
                time.sleep(min(0.25, args.interval - slept))
                slept += 0.25
    logger.info("Watcher stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
