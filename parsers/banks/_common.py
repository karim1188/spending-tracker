from __future__ import annotations

from config.loader import BankRegistry
from models.message import Message
from models.transaction import Transaction
from parsers.base import BankParser
from parsers.generic import extract_fields


class ConfiguredBankParser(BankParser):
    bank_name = "unknown"

    def __init__(self, registry: BankRegistry):
        self.registry = registry

    def can_parse(self, message: Message) -> bool:
        return self.registry.bank_for_sender(message.sender) == self.bank_name

    def parse(self, message: Message) -> Transaction | None:
        if not self.can_parse(message):
            return None
        return extract_fields(message, self.bank_name)
