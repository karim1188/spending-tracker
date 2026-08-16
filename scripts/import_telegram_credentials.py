from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.project_paths import TELEGRAM_CONFIG_PATH, TELEGRAM_EXAMPLE_PATH

DEFAULT_SOURCE = Path(
    r"C:\Users\Yousef\Desktop\my projects\TelegramSignals\Telegram-Autoforwarder\credentials.txt"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy TelegramSignals credentials into this app (not committed)")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    if not args.source.is_file():
        print(f"Credentials file not found: {args.source}")
        return 1
    lines = [line.strip() for line in args.source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 3:
        print("credentials.txt needs api_id, api_hash, phone on three lines")
        return 1
    example = {}
    if TELEGRAM_EXAMPLE_PATH.is_file():
        example = json.loads(TELEGRAM_EXAMPLE_PATH.read_text(encoding="utf-8"))
    payload = {
        **example,
        "api_id": int(lines[0]),
        "api_hash": lines[1],
        "phone": lines[2],
        "chat": example.get("chat", "me"),
        "timezone": example.get("timezone", "Asia/Riyadh"),
        "daily_hour": example.get("daily_hour", 21),
        "daily_minute": example.get("daily_minute", 0),
        "daily_limit_sar": example.get("daily_limit_sar", 200),
        "near_limit_sar": example.get("near_limit_sar", 50),
        "overheat_celsius": example.get("overheat_celsius", 90),
        "overheat_kill": example.get("overheat_kill", True),
    }
    TELEGRAM_CONFIG_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {TELEGRAM_CONFIG_PATH} (gitignored). Chat is Saved Messages (me).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
