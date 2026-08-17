from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from collector.logging_config import get_logger
from notify.menu import (
    menu_button_rows,
    menu_message,
    parse_callback_data,
    parse_menu_command,
    reply_keyboard_rows,
)
from notify.settings import TelegramSettings, load_telegram_settings
from notify.theme import BRAND, card

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
            future = asyncio.run_coroutine_threadsafe(
                self._send_async(text, buttons=buttons if buttons is not None else self._reply_keyboard()),
                self._loop,
            )
            future.result(timeout=60)
            return
        from notify.telegram import send_telegram_oneshot

        send_telegram_oneshot(self.settings, text)

    def send_menu(self) -> None:
        # Inline grid on the card + persistent reply keyboard for tap-only use.
        self.send(menu_message(), buttons=self._menu_with_reply_keyboard())

    def _reply_keyboard(self) -> list:
        from telethon import Button

        return [[Button.text(label) for label in row] for row in reply_keyboard_rows()]

    def _inline_buttons(self) -> list:
        from telethon import Button

        return [[Button.inline(label, data) for label, data in row] for row in menu_button_rows()]

    def _menu_with_reply_keyboard(self) -> list:
        # Prefer the sticky reply keyboard so every action is one press.
        return self._reply_keyboard()

    def _telethon_buttons(self) -> list:
        return self._reply_keyboard()

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
        logger.info("Telegram tap menu ready — reply keyboard stays open in Saved Messages")
        try:
            await self._send_async(menu_message(), buttons=self._reply_keyboard())
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
                await event.respond(menu_message(), buttons=self._reply_keyboard())
                return
            if action == "monthly1":
                text, chart_path = await asyncio.to_thread(self._build_monthly1_report)
                try:
                    if chart_path is not None:
                        caption_limit = 1024
                        if len(text) <= caption_limit:
                            await event.respond(
                                text,
                                file=str(chart_path),
                                buttons=self._reply_keyboard(),
                            )
                        else:
                            await event.respond(
                                file=str(chart_path),
                                buttons=self._reply_keyboard(),
                            )
                            await event.respond(text, buttons=self._reply_keyboard())
                    else:
                        await event.respond(text, buttons=self._reply_keyboard())
                finally:
                    if chart_path is not None:
                        chart_path.unlink(missing_ok=True)
                return
            text = await asyncio.to_thread(self._build_action_text, action)
            # Always re-attach the tap keyboard under every report.
            await event.respond(text, buttons=self._reply_keyboard())
        except Exception as exc:  # noqa: BLE001
            logger.info("Telegram menu action failed (%s): %s", action, exc)
            try:
                await event.respond(
                    card(
                        "Error",
                        subtitle="Could not build that report",
                        sections=[[str(exc)]],
                        badge="failed",
                        footer=BRAND,
                    ),
                    buttons=self._reply_keyboard(),
                )
            except Exception:
                pass

    def _build_action_text(self, action: str) -> str:
        from database.db import SpendingDatabase
        from notify.alerts import format_monthly1_report, format_period_report
        from notify.health import format_health_report, read_health

        if action in {"health", "thermal"}:
            snap = read_health(overheat_threshold=self.settings.overheat_celsius)
            return format_health_report(snap)

        if action == "monthly1":
            raise ValueError("monthly1 uses _build_monthly1_report")

        if action not in {"day", "week", "month", "year"}:
            return menu_message()

        from collector.daily_budget import enrich_month_days

        with SpendingDatabase() as db:
            report = db.period_spending_report(action, timezone_name=self.settings.timezone)
            if action == "day":
                series = enrich_month_days(
                    db.month_day_series(timezone_name=self.settings.timezone),
                    self.settings.daily_limit_sar,
                )
                budget = series.get("daily_budget")
                if budget:
                    report = {
                        **report,
                        "rollover_in": budget["rollover_in"],
                        "daily_allowance": budget["daily_allowance"],
                        "daily_remaining": budget["daily_remaining"],
                    }
        limit = self.settings.daily_limit_sar if action == "day" else None
        return format_period_report(report, limit)

    def _build_monthly1_report(self) -> tuple[str, Path | None]:
        from collector.daily_budget import enrich_month_days
        from database.db import SpendingDatabase
        from notify.alerts import format_monthly1_report
        from notify.charts import write_month_day_chart_png

        with SpendingDatabase() as db:
            series = enrich_month_days(
                db.month_day_series(timezone_name=self.settings.timezone),
                self.settings.daily_limit_sar,
            )
        text = format_monthly1_report(series, self.settings.monthly_limit_sar)
        chart_path: Path | None = None
        try:
            chart_path = write_month_day_chart_png(
                series,
                monthly_limit=self.settings.monthly_limit_sar,
                daily_limit=self.settings.daily_limit_sar,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Monthly1 chart skipped: %s", exc)
        return text, chart_path


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
