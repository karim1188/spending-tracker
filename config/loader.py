from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from collector.project_paths import BANKS_CONFIG_PATH


@dataclass(frozen=True)
class BankConfig:
    name: str
    senders: tuple[str, ...]


class BankRegistry:
    def __init__(self, banks: dict[str, BankConfig]):
        self.banks = banks
        self._sender_to_bank: dict[str, str] = {}
        for bank in banks.values():
            for sender in bank.senders:
                self._sender_to_bank[sender.casefold()] = bank.name

    @classmethod
    def load(cls, path: Path | None = None) -> BankRegistry:
        config_path = path or BANKS_CONFIG_PATH
        with config_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        banks: dict[str, BankConfig] = {}
        for name, body in payload.get("banks", {}).items():
            senders = tuple(str(item) for item in body.get("senders", []) if str(item).strip())
            banks[name] = BankConfig(name=name, senders=senders)
        return cls(banks)

    def bank_for_sender(self, sender: str) -> str | None:
        if not sender:
            return None
        return self._sender_to_bank.get(sender.casefold())

    def configured_senders(self) -> list[str]:
        senders: list[str] = []
        for bank in self.banks.values():
            senders.extend(bank.senders)
        return senders

    def has_any_senders(self) -> bool:
        return any(bank.senders for bank in self.banks.values())
