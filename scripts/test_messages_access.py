from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.imessage_reader import IMessageReader
from collector.logging_config import setup_logging
from collector.macos_access import FDA_HELP


def main() -> int:
    parser = argparse.ArgumentParser(description="Test read-only access to macOS Messages")
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()
    logger = setup_logging()
    reader = IMessageReader(db_path=args.db_path)
    result = reader.test_access()
    if result.ok:
        logger.info(result.message)
        logger.info("Database path: %s", result.path)
        logger.info("Write access: disabled (mode=ro)")
        print("OK — Messages database is readable and will not be modified.")
        return 0
    print(result.message)
    if result.full_disk_access_required:
        print(FDA_HELP)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
