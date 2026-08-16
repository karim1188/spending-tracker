from __future__ import annotations

from dataclasses import dataclass, field

from categorizer.categorizer import Categorizer
from collector.checkpoint import Checkpoint
from collector.imessage_reader import IMessageReader
from collector.logging_config import get_logger, is_debug
from config.loader import BankRegistry
from database.db import SpendingDatabase
from models.message import Message
from parsers.bank_detector import BankDetector

logger = get_logger()


@dataclass
class SyncStats:
    scanned: int = 0
    ignored_non_bank: int = 0
    skipped_duplicate: int = 0
    parsed: int = 0
    stored: int = 0
    unknown: int = 0
    last_message_id: int = 0
    details: list[str] = field(default_factory=list)


class MessageCollector:
    def __init__(
        self,
        db: SpendingDatabase,
        reader: IMessageReader,
        registry: BankRegistry | None = None,
        categorizer: Categorizer | None = None,
        batch_size: int = 100,
    ):
        self.db = db
        self.reader = reader
        self.registry = registry or BankRegistry.load()
        self.detector = BankDetector(self.registry)
        self.categorizer = categorizer or Categorizer(dict(self.db.merchant_rules()))
        self.checkpoint = Checkpoint(db)
        self.batch_size = batch_size
        self._sync_bank_senders()
        self._seed_merchant_rules()

    def sync_once(self, limit: int | None = None) -> SyncStats:
        stats = SyncStats(last_message_id=self.checkpoint.last_message_id())
        logger.info("Last processed message: %s", stats.last_message_id)
        remaining = limit if limit is not None else self.batch_size
        messages = self.reader.get_messages(after_id=stats.last_message_id, limit=remaining)
        logger.info("Found %s new messages", len(messages))
        stats.scanned = len(messages)

        if not self.registry.has_any_senders():
            logger.info(
                "No bank senders configured in config/banks.json. "
                "Run python scripts/list_senders.py then add matching bank short codes."
            )

        for message in messages:
            self._process_message(message, stats)
            self.checkpoint.update(message.id)
            stats.last_message_id = message.id
        return stats

    def _process_message(self, message: Message, stats: SyncStats) -> None:
        if self.db.is_excluded(message.guid):
            stats.skipped_duplicate += 1
            logger.info("Skipping excluded PIN/message GUID")
            return
        if self.db.guid_exists(message.guid):
            stats.skipped_duplicate += 1
            logger.info("Skipping already stored GUID")
            return

        parser = self.detector.detect(message)
        if parser is None:
            stats.ignored_non_bank += 1
            logger.info("Ignoring non-bank sender: %s", message.sender or "(empty)")
            return

        logger.info("Bank message detected: %s", parser.bank_name)
        if is_debug():
            logger.debug("Bank message text: %s", message.text)
        tx = parser.parse(message)
        if tx is None:
            stats.unknown += 1
            logger.info("Bank sender but message is PIN or not financial; not stored")
            return
        stats.parsed += 1
        if tx.transaction_type == "unknown":
            stats.unknown += 1
        tx.category = self.categorizer.categorize(tx.merchant, tx.transaction_type)
        rule = self.db.sender_rule(message.sender)
        if rule:
            if rule["category"]:
                tx.category = rule["category"]
            if rule["bank"]:
                tx.bank = rule["bank"]
        if tx.amount is not None:
            logger.info(
                "Parsed %s: %s %s",
                tx.transaction_type,
                tx.currency or "?",
                f"{tx.amount:.2f}",
            )
        else:
            logger.info("Parsed %s with unknown amount", tx.transaction_type)

        if self.db.insert_transaction(tx):
            stats.stored += 1
            logger.info("Transaction stored")
        else:
            stats.skipped_duplicate += 1
            logger.info("Duplicate GUID on insert, skipped")

    def _sync_bank_senders(self) -> None:
        mapping = {name: list(bank.senders) for name, bank in self.registry.banks.items()}
        self.db.replace_bank_senders(mapping)

    def _seed_merchant_rules(self) -> None:
        from categorizer.categorizer import MERCHANT_RULES

        existing = {pattern for pattern, _ in self.db.merchant_rules()}
        for pattern, category in MERCHANT_RULES.items():
            if pattern not in existing:
                self.db.upsert_merchant_rule(pattern, category)
