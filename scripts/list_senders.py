from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.imessage_reader import IMessageReader, MessagesAccessError
from collector.logging_config import setup_logging
from collector.macos_access import FDA_HELP, mask_sender


def main() -> int:
    parser = argparse.ArgumentParser(description="List incoming Messages senders (read-only)")
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()
    setup_logging()
    reader = IMessageReader(db_path=args.db_path)
    access = reader.test_access()
    if not access.ok:
        print(access.message)
        return 2
    try:
        senders = reader.list_senders()
    except MessagesAccessError as exc:
        print(str(exc))
        if exc.full_disk_access:
            print(FDA_HELP)
        return 2

    print("Incoming SMS senders")
    print()
    if not senders:
        print("No incoming senders found.")
        return 0
    for index, (sender, count) in enumerate(senders, start=1):
        label = mask_sender(sender)
        print(f"{index}. {label:<22} {count} messages")
    print()
    print("Copy matching bank short codes into config/banks.json senders arrays.")
    print("Do not add personal phone numbers unless they are confirmed bank senders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
