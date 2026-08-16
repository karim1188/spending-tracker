from __future__ import annotations

import re
from datetime import datetime

from models.message import Message
from models.transaction import Transaction

CURRENCY_ALIASES = {
    "SAR": "SAR",
    "SR": "SAR",
    "ر.س": "SAR",
    "ر.س.": "SAR",
    "رس": "SAR",
    "ريال": "SAR",
    "ريالا": "SAR",
}

NUMBER = r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)"

AMOUNT_PATTERNS = [
    re.compile(
        NUMBER + r"\s*(?P<currency>SAR|SR|ر\.?\s?س\.?|ريال(?:ا)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<currency>SAR|SR|ر\.?\s?س\.?|ريال(?:ا)?)\s*" + NUMBER,
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:بمبلغ|المبلغ|amount|amt)[:\s]*" + NUMBER,
        re.IGNORECASE,
    ),
]

MERCHANT_PATTERNS = [
    re.compile(r"(?:من|لدى|at|merchant)[:\s]+(?P<merchant>[^\n|]+)", re.IGNORECASE),
]

CARD_PATTERNS = [
    re.compile(r"(?:بطاقة|card|mada|مدى)[^\d]{0,20}(?:\*+|x+|ending)?\s*(?P<last4>\d{4})", re.IGNORECASE),
    re.compile(r"\*+(?P<last4>\d{4})"),
]

ACCOUNT_PATTERNS = [
    re.compile(r"(?:حساب|account)[^\d]{0,20}(?:\*+|x+)?\s*(?P<last4>\d{4})", re.IGNORECASE),
]

BALANCE_PATTERNS = [
    re.compile(
        r"(?:رصيد|balance)[:\s]*(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)",
        re.IGNORECASE,
    ),
]

TYPE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("apple_pay", ("apple pay", "آبل باي", "ابل باي")),
    ("online_purchase", ("online", "أونلاين", "اونلاين", "internet", "e-commerce", "ecommerce")),
    ("cash_withdrawal", ("atm", "سحب نقد", "سحب نقدي", "cash withdrawal", "withdrawal")),
    ("cash_deposit", ("إيداع نقد", "ايداع نقد", "cash deposit", "deposit")),
    ("bank_transfer_in", ("حوالة واردة", "تحويل وارد", "received from", "incoming transfer", "credit transfer")),
    ("bank_transfer_out", ("حوالة صادرة", "تحويل صادر", "sent to", "outgoing transfer", "transfer to")),
    ("salary", ("راتب", "salary")),
    ("refund", ("استرداد", "refund", "reversed", "عكس")),
    ("fee", ("رسوم", "عمولة", "fee", "vat on")),
    ("bill_payment", ("سداد", "فاتورة", "bill payment", "sadad")),
    ("card_purchase", ("شراء", "purchase", "pos", "مدى", "mada", "visa", "mastercard")),
]

OTP_HINTS = (
    "otp",
    "رمز تحقق",
    "رمز التحقق",
    "verification code",
    "one-time",
    "كلمة المرور",
    "password",
    "pin:",
)


def looks_non_financial(text: str) -> bool:
    lowered = text.casefold()
    return any(hint in lowered for hint in OTP_HINTS)


def parse_amount(text: str) -> tuple[float | None, str | None]:
    for pattern in AMOUNT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw_amount = match.group("amount").replace(",", "")
        try:
            amount = float(raw_amount)
        except ValueError:
            continue
        currency = None
        if "currency" in match.groupdict() and match.group("currency"):
            currency = normalize_currency(match.group("currency"))
        elif _has_sar_hint(text):
            currency = "SAR"
        return amount, currency
    return None, None


def normalize_currency(value: str) -> str:
    compact = re.sub(r"\s+", "", value).upper().replace("ر.س.", "ر.س")
    return CURRENCY_ALIASES.get(compact, CURRENCY_ALIASES.get(value.strip(), value.strip().upper()))


def _has_sar_hint(text: str) -> bool:
    lowered = text.casefold()
    return any(token.casefold() in lowered for token in ("sar", "sr", "ريال", "ر.س"))


def parse_merchant(text: str) -> str | None:
    for pattern in MERCHANT_PATTERNS:
        match = pattern.search(text)
        if match:
            merchant = match.group("merchant").strip(" :-|")
            merchant = re.split(r"\s+(?:بطاقة|card|مبلغ|amount|الرصيد|balance)\b", merchant, maxsplit=1)[0]
            merchant = merchant.strip(" :-|")
            if merchant:
                return merchant
    return None


def parse_card_last4(text: str) -> str | None:
    for pattern in CARD_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group("last4")
    return None


def parse_account_last4(text: str) -> str | None:
    for pattern in ACCOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group("last4")
    return None


def parse_balance(text: str) -> float | None:
    match = BALANCE_PATTERNS[0].search(text)
    if not match:
        return None
    try:
        return float(match.group("amount").replace(",", ""))
    except ValueError:
        return None


def infer_transaction_type(text: str) -> str:
    lowered = text.casefold()
    for tx_type, keywords in TYPE_KEYWORDS:
        if any(keyword.casefold() in lowered for keyword in keywords):
            return tx_type
    return "unknown"


def extract_fields(message: Message, bank: str) -> Transaction | None:
    text = (message.text or "").strip()
    if not text or looks_non_financial(text):
        return None
    amount, currency = parse_amount(text)
    tx_type = infer_transaction_type(text)
    merchant = parse_merchant(text)
    if amount is None and tx_type == "unknown" and not merchant:
        return None
    if amount is not None and currency is None and _has_sar_hint(text):
        currency = "SAR"
    return Transaction(
        source_message_guid=message.guid,
        bank=bank,
        sender=message.sender,
        transaction_type=tx_type,
        amount=amount,
        currency=currency,
        merchant=merchant,
        card_last4=parse_card_last4(text),
        account_last4=parse_account_last4(text),
        transaction_time=message.timestamp if isinstance(message.timestamp, datetime) else None,
        balance=parse_balance(text),
        raw_message=text if _debug_raw_allowed() else text,
    )


def _debug_raw_allowed() -> bool:
    return True
