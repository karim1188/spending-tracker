from __future__ import annotations

import asyncio
from collections.abc import Callable

from notify.settings import TelegramSettings


def send_telegram(settings: TelegramSettings, text: str) -> None:
    asyncio.run(_send(settings, text))


async def _send(settings: TelegramSettings, text: str) -> None:
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
    except ImportError as exc:
        raise RuntimeError("Install telegram extra: pip install -e '.[telegram]'") from exc

    client = TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. Run python3 scripts/telegram_login.py on this Mac."
            )
        await client.send_message(settings.chat, text)
    except SessionPasswordNeededError as exc:
        raise RuntimeError("Telegram 2FA is on. Run python3 scripts/telegram_login.py") from exc
    finally:
        await client.disconnect()


def sender_from_settings(settings: TelegramSettings | None) -> Callable[[str], None] | None:
    if settings is None or not settings.ready:
        return None

    def _send_text(text: str) -> None:
        send_telegram(settings, text)

    return _send_text
