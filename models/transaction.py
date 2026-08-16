from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


TRANSACTION_TYPES = (
    "card_purchase",
    "online_purchase",
    "apple_pay",
    "cash_withdrawal",
    "bank_transfer_out",
    "bank_transfer_in",
    "salary",
    "refund",
    "fee",
    "cash_deposit",
    "bill_payment",
    "unknown",
)


@dataclass
class Transaction:
    source_message_guid: str
    bank: str | None = None
    sender: str | None = None
    transaction_type: str = "unknown"
    amount: float | None = None
    currency: str | None = None
    merchant: str | None = None
    card_last4: str | None = None
    account_last4: str | None = None
    transaction_time: datetime | None = None
    balance: float | None = None
    category: str | None = None
    subcategory: str | None = None
    raw_message: str | None = None
    created_at: datetime | None = None
    id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "source_message_guid": self.source_message_guid,
            "bank": self.bank,
            "sender": self.sender,
            "transaction_type": self.transaction_type,
            "amount": self.amount,
            "currency": self.currency,
            "merchant": self.merchant,
            "card_last4": self.card_last4,
            "account_last4": self.account_last4,
            "transaction_time": (
                self.transaction_time.isoformat(sep=" ") if self.transaction_time else None
            ),
            "balance": self.balance,
            "category": self.category,
            "subcategory": self.subcategory,
            "raw_message": self.raw_message,
        }
