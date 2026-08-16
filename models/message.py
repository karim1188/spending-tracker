from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Message:
    id: int
    guid: str
    sender: str
    text: str
    timestamp: datetime
    service: str
    is_from_me: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        raw_ts = data["timestamp"]
        if isinstance(raw_ts, datetime):
            timestamp = raw_ts
        else:
            timestamp = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        return cls(
            id=int(data["id"]),
            guid=str(data["guid"]),
            sender=str(data.get("sender") or ""),
            text=str(data.get("text") or ""),
            timestamp=timestamp,
            service=str(data.get("service") or "Unknown"),
            is_from_me=bool(data.get("is_from_me", False)),
        )
