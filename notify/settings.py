from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from collector.project_paths import TELEGRAM_CONFIG_PATH


@dataclass
class TelegramSettings:
    api_id: int
    api_hash: str
    phone: str
    chat: str = "me"
    timezone: str = "Asia/Riyadh"
    daily_hour: int = 21
    daily_minute: int = 0
    daily_limit_sar: float = 200.0
    near_limit_sar: float = 50.0
    monthly_limit_sar: float = 6000.0
    overheat_celsius: float = 90.0
    overheat_kill: bool = True
    session_path: Path = Path("config/telegram")

    @property
    def ready(self) -> bool:
        return bool(self.api_id and self.api_hash and self.phone)


def load_telegram_settings(path: Path | None = None) -> TelegramSettings | None:
    config_path = Path(path) if path else TELEGRAM_CONFIG_PATH
    data: dict = {}
    if config_path.is_file():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    api_id = os.environ.get("TELEGRAM_API_ID") or data.get("api_id")
    api_hash = os.environ.get("TELEGRAM_API_HASH") or data.get("api_hash")
    phone = os.environ.get("TELEGRAM_PHONE") or data.get("phone")
    if not api_id or not api_hash or not phone:
        return None
    try:
        api_id_int = int(api_id)
    except (TypeError, ValueError):
        return None
    session_path = config_path.with_name("telegram")
    return TelegramSettings(
        api_id=api_id_int,
        api_hash=str(api_hash).strip(),
        phone=str(phone).strip(),
        chat=str(os.environ.get("TELEGRAM_CHAT") or data.get("chat") or "me"),
        timezone=str(data.get("timezone") or "Asia/Riyadh"),
        daily_hour=int(data.get("daily_hour") or 21),
        daily_minute=int(data.get("daily_minute") or 0),
        daily_limit_sar=float(data.get("daily_limit_sar") or 200),
        near_limit_sar=float(data.get("near_limit_sar") or 50),
        monthly_limit_sar=float(data.get("monthly_limit_sar") or 6000),
        overheat_celsius=float(data.get("overheat_celsius") or 90),
        overheat_kill=bool(data.get("overheat_kill", True)),
        session_path=session_path,
    )
