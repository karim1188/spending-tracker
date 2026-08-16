from __future__ import annotations

from abc import ABC, abstractmethod

from models.message import Message
from models.transaction import Transaction


class BankParser(ABC):
    bank_name: str = "unknown"

    @abstractmethod
    def can_parse(self, message: Message) -> bool:
        ...

    @abstractmethod
    def parse(self, message: Message) -> Transaction | None:
        ...
