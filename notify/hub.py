from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from collector.logging_config import get_logger
from notify.menu import menu_button_rows, menu_message, parse_callback_data, parse_menu_command
from notify.settings import TelegramSettings, load_telegram_settings

logger = get_logger()

_hub_lock = threading.Lock()
_hub: "TelegramHub | None" = None


def get_hub() -> "TelegramHub | None":
    with _hub_lock:
        return _hub


def set_hub(hub: "TelegramHub | None") -> None:
    global _hub
    with _hub_lock:
        _hub = hub


class TelegramHub:
    """One Telethon client for outbound alerts and inbound report menu."""

    def __init__(self, settings: TelegramSettings) -> None:
        self.settings = settings
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: Any = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._client is not None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="telegram-hub", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=45)

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        client = self._client
        if loop and client and loop.is_running():
            asyncio.run_coroutine_threadsafe(client.disconnect(), loop)
        if self._thread:
            self._thread.join(timeout=5)
        self._ready.clear()

    def send(self, text: str, *, buttons: list | None = None) -> None:
        if not text:
            return
        if self.ready and self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(self._send_async(text, buttons=buttons), self._loop)
            future.result(timeout=60)
            return
        from notify.telegram import send_telegram_oneshot

        send_telegram_oneshot(self.settings, text)

    def send_menu(self) -> None:
        self.send(menu_message(), buttons=self._telethon_buttons())

    def _telethon_buttons(self) -> list:
        from telethon import Button

        return [[Button.inline(label, data) for label, data in row] for row in menu_button_rows()]

    async def _send_async(self, text: str, *, buttons: list | None = None) -> None:
        assert self._client is not None
        kwargs = {}
        if buttons is not None:
            kwargs["buttons"] = buttons
        await self._client.send_message(self.settings.chat, text, **kwargs)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._amain())
        except Exception as exc:  # noqa: BLE001
            logger.info("Telegram hub stopped: %s", exc)
        finally:
            self._ready.clear()
            self._client = None
            self._loop = None

    async def _amain(self) -> None:
        from telethon import TelegramClient, events
        from telethon.errors import SessionPasswordNeededError

        self._loop = asyncio.get_running_loop()
        client = TelegramClient(str(self.settings.session_path), self.settings.api_id, self.settings.api_hash)
        self._client = client
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized. Run python3 scripts/telegram_login.py")
        try:
            me = await client.get_me()
        except SessionPasswordNeededError as exc:
            raise RuntimeError("Telegram 2FA is on. Run python3 scripts/telegram_login.py") from exc

        @client.on(events.NewMessage())
        async def on_message(event) -> None:  # type: ignore[no-untyped-def]
            if self._stop.is_set():
                return
            if not await self._is_allowed_message(event, me.id):
                return
            action = parse_menu_command(event.raw_text)
            if action is None:
                return
            await self._handle_action(event, action)

        @client.on(events.CallbackQuery)
        async def on_callback(event) -> None:  # type: ignore[no-untyped-def]
            if self._stop.is_set():
                return
            if event.sender_id not in {None, me.id}:
                await event.answer("Not allowed", alert=True)
                return
            action = parse_callback_data(event.data)
            if action is None:
                await event.answer()
                return
            await event.answer()
            await self._handle_action(event, action)

        self._ready.set()
        logger.info("Telegram menu ready — send menu in Saved Messages for Day/Week/Month/Year")
        try:
            await self._send_async(menu_message(), buttons=self._telethon_buttons())
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not send opening menu: %s", exc)
        try:
            await client.run_until_disconnected()
        finally:
            pass

    async def _is_allowed_message(self, event, my_id: int) -> bool:
        # Only Saved Messages / configured private chat; ignore long report dumps.
        text = (event.raw_text or "").strip()
        if len(text) > 64:
            return False
        chat = self.settings.chat
        if chat in {"me", "self", ""}:
            if event.chat_id != my_id:
                return False
        else:
            try:
                entity = await self._client.get_entity(chat)
                if event.chat_id != getattr(entity, "id", None):
                    return False
            except Exception:
                return False
        sender = event.sender_id
        if sender is not None and sender != my_id:
            return False
        return True

    async def _handle_action(self, event, action: str) -> None:
        try:
            if action == "menu":
                await event.respond(menu_message(), buttons=self._telethon_buttons())
                return
            text = await asyncio.to_thread(self._build_action_text, action)
            await event.respond(text)
        except Exception as exc:  # noqa: BLE001
            logger.info("Telegram menu action failed (%s): %s", action, exc)
            try:
                await event.respond(f"Could not build that report: {exc}")
            except Exception:
                pass

    def _build_action_text(self, action: str) -> str:
        from database.db import SpendingDatabase
        from notify.alerts import format_period_report
        from notify.health import format_health_report, read_health

        if action in {"health", "thermal"}:
            snap = read_health(overheat_threshold=self.settings.overheat_celsius)
            return format_health_report(snap)

        if action not in {"day", "week", "month", "year"}:
            return menu_message()

        with SpendingDatabase() as db:
            report = db.period_spending_report(action, timezone_name=self.settings.timezone)
        limit = self.settings.daily_limit_sar if action == "day" else None
        return format_period_report(report, limit)


def start_telegram_hub(settings: TelegramSettings | None = None) -> TelegramHub | None:
    settings = settings if settings is not None else load_telegram_settings()
    if settings is None or not settings.ready:
        return None
    try:
        import telethon  # noqa: F401
    except ImportError:
        logger.info("Telegram hub off: pip install -e '.[telegram]'")
        return None
    hub = TelegramHub(settings)
    set_hub(hub)
    hub.start()
    if not hub.ready:
        logger.info("Telegram hub did not become ready (check session / telegram_login.py)")
        set_hub(None)
        return None
    return hub


def hub_sender(settings: TelegramSettings | None = None) -> Callable[[str], None] | None:
    settings = settings if settings is not None else load_telegram_settings()
    if settings is None or not settings.ready:
        return None
    hub = get_hub()
    if hub is not None and hub.ready:
        return hub.send

    def _send(text: str) -> None:
        current = get_hub()
        if current is not None and current.ready:
            current.send(text)
            return
        from notify.telegram import send_telegram_oneshot

        send_telegram_oneshot(settings, text)

    return _send
