from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.db import SpendingDatabase
from notify.alerts import format_day_report, tick
from notify.settings import load_telegram_settings
from notify.telegram import send_telegram


def main() -> int:
    parser = argparse.ArgumentParser(description="Send today's spending to Telegram now")
    parser.add_argument("--force", action="store_true", help="Send even if today's digest already went out")
    args = parser.parse_args()
    settings = load_telegram_settings()
    if settings is None:
        print("Missing config/telegram.json")
        return 1
    with SpendingDatabase() as db:
        if args.force:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from collector.daily_budget import enrich_month_days

            day = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
            now = datetime.now(ZoneInfo(settings.timezone))
            report = db.day_spending_report(day)
            series = enrich_month_days(
                db.month_day_series(timezone_name=settings.timezone, now=now),
                settings.daily_limit_sar,
            )
            send_telegram(
                settings,
                format_day_report(report, settings.daily_limit_sar, budget=series.get("daily_budget")),
            )
            print("Sent today's spending.")
            return 0
        sent = tick(db, settings=settings)
        print("Sent:" , ", ".join(sent) if sent else "nothing new (already sent today, or under the warning and before digest hour).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
