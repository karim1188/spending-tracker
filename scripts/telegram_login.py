from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notify.settings import load_telegram_settings


async def main() -> int:
    settings = load_telegram_settings()
    if settings is None:
        print("Missing config/telegram.json. On this PC run:")
        print("  python scripts/import_telegram_credentials.py")
        print("On the Mac, copy that gitignored file over, then run this login script.")
        return 1
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
    except ImportError:
        print("Install Telethon: pip install -e '.[telegram]'")
        return 1
    client = TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.send_code_request(settings.phone)
        code = input("Enter the Telegram login code: ").strip()
        try:
            await client.sign_in(settings.phone, code)
        except SessionPasswordNeededError:
            password = input("Two-step verification password: ")
            await client.sign_in(password=password)
    await client.send_message(settings.chat, "Spending tracker connected. Daily totals and the SAR 200 warning will come here.")
    await client.disconnect()
    print("Telegram session saved. Alerts will send to Saved Messages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
