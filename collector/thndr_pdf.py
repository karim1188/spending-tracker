from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import re
from typing import Iterable

ISIN_RE = re.compile(r"((?:EGS|AEE|AEC|US|SA)[A-Z0-9]{8,12})")
SYMBOL_TX_RE = re.compile(
    r"(?P<name>.+?)\s+(?P<symbol>[A-Z]{2,12})\s+(?P<ttype>buy|sell)\s+"
    r"(?P<avg>[\d,]+\.?\d*)\s*(?P<cur>EGP|AED|SAR|USD)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")
CURRENCIES = frozenset({"EGP", "AED", "SAR", "USD"})
SKIP_NAME_PREFIXES = (
    "symbol",
    "transaction",
    "isin",
    "total",
    "fees",
    "grand",
    "quantity",
    "price",
    "value",
    "average",
    "code",
)
THNDR_SENDER_HINTS = ("thndr.app", "system.thndr.app", "thndr")
# Simple Gmail queries only — nested quotes break IMAP X-GM-RAW quoting.
THNDR_GMAIL_QUERIES = (
    "from:thndr.app has:attachment filename:pdf",
    "from:system.thndr.app has:attachment filename:pdf",
    "subject:thndr has:attachment filename:pdf",
    "thndr has:attachment filename:pdf",
    "from:thndr.app",
    "subject:thndr",
    "thndr",
)
THNDR_GMAIL_QUERY = THNDR_GMAIL_QUERIES[0]


@dataclass(frozen=True)
class InvoiceTrade:
    date: date
    market: str
    isin: str
    ticker: str
    symbol: str | None
    name: str
    type: str
    quantity: int
    price: float
    value: float
    fees: float
    total: float
    currency: str
    file: str


@dataclass
class PdfParseResult:
    filename: str
    kind: str
    date: date | None
    trades: list[InvoiceTrade] = field(default_factory=list)
    preview: str = ""
    error: str | None = None


def is_skip_filename(filename: str) -> bool:
    lower = (filename or "").lower()
    return "contract" in lower or "agreement" in lower


def classify_pdf(text: str, filename: str = "") -> str:
    text_lower = (text or "").lower()
    fname = (filename or "").lower()
    if "e-statement" in fname or ("statement" in fname and "invoice" not in fname):
        return "statement"
    if "e-invoice" in fname or ("invoice" in fname and "statement" not in fname):
        return "invoice"
    has_statement = any(
        token in text_lower
        for token in (
            "monthly statement",
            "account statement",
            "statement of account",
            "e-statement",
            "portfolio statement",
            "holding statement",
        )
    )
    has_invoice = (
        "invoice" in text_lower
        and ("security name" in text_lower or "isin" in text_lower)
        and ("transaction type" in text_lower or "buy" in text_lower or "sell" in text_lower)
    )
    if has_statement and not has_invoice:
        return "statement"
    if has_invoice:
        return "invoice"
    return "other"


def detect_market(text: str) -> str:
    if "AED" in text:
        return "ADX"
    if "SAR" in text:
        return "TDWL"
    if "USD" in text and "EGP" not in text:
        return "USA"
    if "EGP" in text:
        return "EGX"
    return "Unknown"


def extract_pdf_text(path: Path, *, max_pages: int | None = None) -> str:
    return extract_pdf_bytes(path.read_bytes(), max_pages=max_pages)


def extract_pdf_bytes(data: bytes, *, max_pages: int | None = None) -> str:
    import io
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        return "\n".join(page.extract_text() or "" for page in pages)


def extract_pdf_date(text: str) -> date | None:
    match = DATE_RE.search(text or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_invoice_text(full_text: str, *, filename: str = "") -> list[InvoiceTrade]:
    """Parse a Thndr buy/sell invoice. Same fields the portfolio app stores as stocks."""
    text = (full_text or "").lower()
    if "invoice" not in text or "security name" not in text:
        return []
    has_isin = bool(ISIN_RE.search(full_text))
    has_symbol_code = bool(re.search(r"\bthndrgold\b", text)) or (
        "symbol code" in text and re.search(r"\b(buy|sell)\b", text)
    )
    has_ticker_line = bool(SYMBOL_TX_RE.search(full_text))
    if not has_isin and not has_symbol_code and not has_ticker_line:
        return []
    if "transaction type" not in text and "buy" not in text and "sell" not in text:
        return []
    if "quantity" not in text or "price" not in text:
        return []
    if "total fees" not in text and "grand total" not in text:
        return []

    invoice_date = extract_pdf_date(full_text)
    if invoice_date is None:
        return []

    results: list[InvoiceTrade] = []
    for block in full_text.split("Security Name")[1:]:
        trade = _parse_security_block(block, invoice_date, filename)
        if trade is not None:
            results.append(trade)
    return results


def parse_pdf_file(path: Path) -> PdfParseResult:
    return parse_pdf_bytes(path.read_bytes(), filename=path.name)


def parse_pdf_bytes(data: bytes, *, filename: str) -> PdfParseResult:
    if is_skip_filename(filename):
        return PdfParseResult(filename=filename, kind="skipped", date=None, preview="non-trade PDF")
    try:
        full_text = extract_pdf_bytes(data)
    except Exception as exc:
        return PdfParseResult(filename=filename, kind="error", date=None, error=str(exc))
    kind = classify_pdf(full_text, filename)
    pdf_date = extract_pdf_date(full_text)
    trades = parse_invoice_text(full_text, filename=filename) if kind == "invoice" else []
    preview = " ".join(full_text.split())[:240]
    return PdfParseResult(
        filename=filename,
        kind=kind,
        date=pdf_date,
        trades=trades,
        preview=preview,
    )


def aggregate_stocks(trades: Iterable[InvoiceTrade]) -> list[dict]:
    """Net quantity per ISIN — the stock rows the portfolio would create/update."""
    grouped: dict[str, dict] = {}
    for trade in trades:
        row = grouped.setdefault(
            trade.isin,
            {
                "isin": trade.isin,
                "symbol": trade.symbol or trade.ticker,
                "name": trade.name,
                "market": trade.market,
                "currency": trade.currency,
                "quantity": 0,
                "buys": 0,
                "sells": 0,
                "last_price": trade.price,
                "last_date": trade.date.isoformat(),
            },
        )
        signed = trade.quantity if trade.type.lower() == "buy" else -trade.quantity
        row["quantity"] += signed
        if trade.type.lower() == "buy":
            row["buys"] += trade.quantity
        else:
            row["sells"] += trade.quantity
        row["last_price"] = trade.price
        row["last_date"] = trade.date.isoformat()
        if trade.symbol:
            row["symbol"] = trade.symbol
        if trade.name and trade.name != "Unknown Security":
            row["name"] = trade.name
    return sorted(grouped.values(), key=lambda item: item["symbol"] or item["isin"])


def _parse_num(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = str(text).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _numeric_parts(line: str) -> list[float]:
    parts = line.replace(",", "").split()
    numbers: list[float] = []
    for part in parts:
        if "-" in part or len(part) > 15:
            continue
        if part.upper() in CURRENCIES:
            continue
        if re.match(r"^\d+\.?\d*$", part):
            numbers.append(float(part))
    return numbers


def _parse_security_block(block: str, invoice_date: date, filename: str) -> InvoiceTrade | None:
    isin_match = ISIN_RE.search(block)
    isin = isin_match.group(1) if isin_match else None
    symbol_code = None
    if not isin:
        gold = re.search(r"\b(thndrgold|[a-z]{3,20}gold)\b", block, re.IGNORECASE)
        if gold:
            symbol_code = gold.group(1).lower()
            isin = f"SYNTH-{symbol_code.upper()}"
        else:
            ticker_m = SYMBOL_TX_RE.search(block)
            if not ticker_m:
                return None
            symbol_code = ticker_m.group("symbol").upper()
            if symbol_code in {"EGP", "AED", "SAR", "USD", "BUY", "SELL", "CODE", "TYPE"}:
                return None
            isin = f"SYNTH-{symbol_code}"

    name = _extract_name(block, isin_match, isin, symbol_code)
    ttype = _extract_type(block, isin_match)
    if not ttype:
        return None

    qty, price, value = _extract_qty_price_value(block)
    if qty is None or price is None:
        return None
    if value is None:
        value = price * qty

    fees_match = re.search(r"Total Fees\s+([\d,]+\.?\d*)", block)
    fees = _parse_num(fees_match.group(1)) if fees_match else 0.0
    total_match = re.search(r"Grand Total\s+([\d,]+\.?\d*)", block)
    total = _parse_num(total_match.group(1)) if total_match else value + (fees or 0.0)

    if re.search(r"\bAED\b", block):
        currency, market = "AED", "ADX"
    elif re.search(r"\bSAR\b", block):
        currency, market = "SAR", "TDWL"
    elif re.search(r"\bUSD\b", block) and not re.search(r"\bEGP\b", block):
        currency, market = "USD", "USA"
    else:
        currency, market = "EGP", "EGX"

    symbol = symbol_code.upper() if symbol_code else None
    if symbol in CURRENCIES:
        symbol = None
    ticker = symbol or isin
    return InvoiceTrade(
        date=invoice_date,
        market=market,
        isin=isin,
        ticker=str(ticker),
        symbol=symbol,
        name=name,
        type=ttype,
        quantity=int(qty),
        price=float(price),
        value=float(value),
        fees=float(fees or 0.0),
        total=float(total or 0.0),
        currency=currency,
        file=filename,
    )


def _extract_type(block: str, isin_match: re.Match[str] | None) -> str | None:
    if isin_match:
        after_isin = block[isin_match.end() :].strip()
        type_match = re.search(r"^\s*(\w+)", after_isin)
        if type_match and type_match.group(1).lower() in {"buy", "sell"}:
            return type_match.group(1).capitalize()
    type_match = re.search(r"\b(Buy|Sell)\b", block, re.IGNORECASE)
    if type_match:
        return type_match.group(1).capitalize()
    return None


def _extract_qty_price_value(block: str) -> tuple[int | None, float | None, float | None]:
    lines = block.split("\n")
    qty = price = value = None
    for index, line in enumerate(lines):
        if "Transaction No." in line and "Quantity" in line and index + 1 < len(lines):
            numbers = _numeric_parts(lines[index + 1].strip())
            if len(numbers) >= 2:
                qty = int(numbers[0])
                price = numbers[1]
                value = numbers[2] if len(numbers) >= 3 else qty * price
            break
    if qty is None or price is None:
        for index, line in enumerate(lines):
            if "Total Quantity" in line and "Average Price" in line and index + 1 < len(lines):
                numbers = _numeric_parts(lines[index + 1].strip())
                if len(numbers) >= 2:
                    qty = qty if qty is not None else int(numbers[0])
                    price = price if price is not None else numbers[1]
                    if value is None and len(numbers) >= 3:
                        value = numbers[2]
                break
    if qty is None:
        qty_match = re.search(r"Total Quantity\s+(\d+)", block) or re.search(r"Quantity\s+(\d+)", block)
        if qty_match:
            qty = int(qty_match.group(1))
    if price is None:
        price_match = re.search(r"Average Price\s+([\d,]+\.?\d*)", block) or re.search(
            r"Price\s+([\d,]+\.?\d*)", block
        )
        if price_match:
            price = _parse_num(price_match.group(1))
    if value is None:
        value_match = re.search(r"Total Cost\s+([\d,]+\.?\d*)", block) or re.search(
            r"Value\s+([\d,]+\.?\d*)", block
        )
        if value_match:
            value = _parse_num(value_match.group(1))
    return qty, price, value


def _extract_name(
    block: str,
    isin_match: re.Match[str] | None,
    isin: str | None,
    symbol_code: str | None,
) -> str:
    lines = block.split("\n")
    isin_line_idx = None
    for index, line in enumerate(lines):
        if isin_match and isin and isin in line:
            isin_line_idx = index
            break
        if symbol_code and symbol_code.lower() in line.lower():
            isin_line_idx = index
            break
    if isin_line_idx is None:
        return symbol_code or "Unknown Security"

    name_parts: list[str] = []
    for line in lines[:isin_line_idx]:
        cleaned = _clean_name_line(line, symbol_code)
        if cleaned:
            name_parts.append(cleaned)

    isin_line = lines[isin_line_idx].strip()
    if isin_match and isin and isin in isin_line:
        before = isin_line[: isin_line.find(isin)].strip(" :-")
        before = _clean_name_line(before, symbol_code)
        if before:
            name_parts.append(before)
    elif symbol_code and symbol_code.lower() in isin_line.lower():
        before = re.split(re.escape(symbol_code), isin_line, flags=re.IGNORECASE)[0].strip()
        before = _clean_name_line(before, symbol_code)
        if before:
            name_parts.append(before)

    for line in lines[isin_line_idx + 1 : isin_line_idx + 4]:
        stripped = line.strip()
        if stripped.lower().startswith(("transaction no", "quantity", "price", "value", "total quantity")):
            break
        cleaned = _clean_name_line(stripped, symbol_code)
        if cleaned:
            name_parts.append(cleaned)

    name = re.sub(r"\s+", " ", " ".join(name_parts)).strip()
    if isin:
        name = re.sub(r"\s*(EGS|AEE|AEC|US|SA)[A-Z0-9]{8,12}\s*", "", name).strip()
    if not name or len(name) < 2:
        return symbol_code or "Unknown Security"
    return name


def _clean_name_line(line: str, symbol_code: str | None) -> str | None:
    text = (line or "").strip()
    if not text:
        return None
    lower = text.lower()
    if lower.startswith(SKIP_NAME_PREFIXES) or lower in {"buy", "sell"}:
        return None
    if re.match(r"^[\d\.\s]+(EGP|AED|SAR|USD)$", text, re.IGNORECASE):
        return None
    if re.match(r"^[A-Z0-9\-]+$", text) and len(text) < 20:
        return None
    text = re.sub(r"\s+(Buy|Sell).*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+\d+\.?\d*\s+(EGP|AED|SAR|USD)\s*$", "", text, flags=re.IGNORECASE)
    if symbol_code:
        text = re.sub(re.escape(symbol_code), "", text, flags=re.IGNORECASE).strip()
    text = text.strip()
    return text if len(text) > 1 else None
