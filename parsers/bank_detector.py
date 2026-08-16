from __future__ import annotations

from config.loader import BankRegistry
from models.message import Message
from parsers.banks.alinma import AlinmaParser
from parsers.banks.alrajhi import AlRajhiParser
from parsers.banks.mobily import MobilyPayParser
from parsers.banks.riyad import RiyadParser
from parsers.banks.sab import SabParser
from parsers.banks.snb import SnbParser
from parsers.base import BankParser

DEFAULT_PARSERS: tuple[type[BankParser], ...] = (
    SnbParser,
    AlRajhiParser,
    RiyadParser,
    SabParser,
    AlinmaParser,
    MobilyPayParser,
)


class BankDetector:
    def __init__(self, registry: BankRegistry, parsers: list[BankParser] | None = None):
        self.registry = registry
        self.parsers = parsers or [cls(registry) for cls in DEFAULT_PARSERS]

    def detect(self, message: Message) -> BankParser | None:
        bank = self.registry.bank_for_sender(message.sender)
        if not bank:
            return None
        for parser in self.parsers:
            if parser.bank_name == bank and parser.can_parse(message):
                return parser
        return None

    def is_bank_sender(self, sender: str) -> bool:
        return self.registry.bank_for_sender(sender) is not None
