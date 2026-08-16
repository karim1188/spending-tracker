from __future__ import annotations

CATEGORIES = (
    "Food & Dining",
    "Groceries",
    "Transportation",
    "Shopping",
    "Bills & Utilities",
    "Subscriptions",
    "Entertainment",
    "Travel",
    "Health",
    "Education",
    "Housing",
    "Transfers",
    "Cash",
    "Salary",
    "Fees",
    "Other",
)

MERCHANT_RULES: dict[str, str] = {
    "HUNGERSTATION": "Food & Dining",
    "HUNGER STATION": "Food & Dining",
    "JAHEZ": "Food & Dining",
    "KEETA": "Food & Dining",
    "MRSOOL": "Food & Dining",
    "TOYOU": "Food & Dining",
    "STARBUCKS": "Food & Dining",
    "MCDONALD": "Food & Dining",
    "UBER": "Transportation",
    "CAREEM": "Transportation",
    "LYFT": "Transportation",
    "AMAZON": "Shopping",
    "NOON": "Shopping",
    "NAMSHI": "Shopping",
    "STC": "Bills & Utilities",
    "MOBILY": "Bills & Utilities",
    "ZAIN": "Bills & Utilities",
    "NETFLIX": "Subscriptions",
    "SPOTIFY": "Subscriptions",
    "APPLE.COM/BILL": "Subscriptions",
    "CINEMA": "Entertainment",
    "VOX": "Entertainment",
    "SAUDIA": "Travel",
    "FLYDUBAI": "Travel",
    "BOOKING": "Travel",
    "ALMOOSA": "Health",
    "NADEC": "Groceries",
    "PANDA": "Groceries",
    "TAMIMI": "Groceries",
    "CARREFOUR": "Groceries",
}

TYPE_CATEGORY = {
    "bank_transfer_out": "Transfers",
    "bank_transfer_in": "Transfers",
    "wallet_topup": "Transfers",
    "salary": "Salary",
    "fee": "Fees",
    "cash_withdrawal": "Cash",
    "cash_deposit": "Cash",
    "bill_payment": "Bills & Utilities",
}

TYPE_FIRST = {
    "salary",
    "bank_transfer_in",
    "bank_transfer_out",
    "wallet_topup",
    "fee",
    "cash_withdrawal",
    "cash_deposit",
}


class Categorizer:
    """Replaceable local rule-based categorizer. No external LLM."""

    def __init__(self, extra_rules: dict[str, str] | None = None):
        self.rules = {key.upper(): value for key, value in MERCHANT_RULES.items()}
        if extra_rules:
            self.rules.update({key.upper(): value for key, value in extra_rules.items()})

    def categorize(
        self,
        merchant: str | None,
        transaction_type: str | None = None,
    ) -> str:
        if transaction_type in TYPE_FIRST and transaction_type in TYPE_CATEGORY:
            return TYPE_CATEGORY[transaction_type]
        if merchant:
            haystack = merchant.upper()
            for pattern, category in sorted(self.rules.items(), key=lambda item: len(item[0]), reverse=True):
                if pattern in haystack:
                    return category
        if transaction_type in TYPE_CATEGORY:
            return TYPE_CATEGORY[transaction_type]
        return "Other"
