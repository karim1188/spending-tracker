from __future__ import annotations

from datetime import date
from email.message import EmailMessage
import imaplib

from collector.gmail_reader import GmailReader, iter_pdf_attachments
from collector.thndr_pdf import (
    aggregate_stocks,
    classify_pdf,
    is_skip_filename,
    parse_invoice_text,
)


SAMPLE_INVOICE = """
Thndr E-Invoice
Date 09/12/2025
Security Name
Commercial International Bank
EGS60121C018 Buy
Transaction No. Quantity Price Value
N20250915-476 5 1.78 EGP 8.90 EGP
Total Quantity Average Price Total Cost
5 1.78 EGP 8.90 EGP
Total Fees 0.50
Grand Total 9.40
"""

SAMPLE_STATEMENT = """
Your monthly E-statement
Account statement
Portfolio statement
09/12/2025
"""


def test_classify_invoice_and_statement():
    assert classify_pdf(SAMPLE_INVOICE, "Your Thndr Invoice (2025-12-09).pdf") == "invoice"
    assert classify_pdf(SAMPLE_STATEMENT, "Your monthly E-statement - Nov 2025.pdf") == "statement"


def test_skip_contracts():
    assert is_skip_filename("Digital Contract.pdf") is True
    assert is_skip_filename("Your Thndr Invoice.pdf") is False


def test_parse_invoice_creates_stock_trade():
    trades = parse_invoice_text(SAMPLE_INVOICE, filename="invoice.pdf")
    assert len(trades) == 1
    trade = trades[0]
    assert trade.date == date(2025, 12, 9)
    assert trade.isin == "EGS60121C018"
    assert trade.type == "Buy"
    assert trade.quantity == 5
    assert trade.price == 1.78
    assert trade.currency == "EGP"
    assert trade.market == "EGX"
    assert "Commercial International Bank" in trade.name


def test_aggregate_stocks_nets_buys_and_sells():
    buy = parse_invoice_text(SAMPLE_INVOICE, filename="buy.pdf")[0]
    sell_text = SAMPLE_INVOICE.replace("Buy", "Sell").replace("buy", "sell")
    sell = parse_invoice_text(sell_text, filename="sell.pdf")[0]
    stocks = aggregate_stocks([buy, sell])
    assert len(stocks) == 1
    assert stocks[0]["quantity"] == 0
    assert stocks[0]["buys"] == 5
    assert stocks[0]["sells"] == 5


def test_iter_pdf_attachments_from_mime():
    msg = EmailMessage()
    msg["From"] = "Thndr <no-reply@system.thndr.app>"
    msg["Subject"] = "Your Thndr Invoice (2025-12-09)"
    msg["Date"] = "Tue, 09 Dec 2025 13:32:35 +0000"
    msg.set_content("Invoice attached")
    msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="invoice.pdf")
    found = iter_pdf_attachments(msg)
    assert len(found) == 1
    assert found[0][0] == "invoice.pdf"
    assert found[0][1].startswith(b"%PDF")


class FakeUidImap:
    def __init__(self):
        self.selected = None
        self.logged_out = False

    def login(self, user, password):
        return "OK", [b""]

    def list(self, directory='""', pattern="*"):
        return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"']

    def select(self, mailbox, readonly=False):
        self.selected = mailbox
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"99"]
        if command == "FETCH":
            msg = EmailMessage()
            msg["From"] = "Thndr <no-reply@system.thndr.app>"
            msg["Subject"] = "Your Thndr Invoice"
            msg["Date"] = "Tue, 09 Dec 2025 13:32:35 +0000"
            msg.set_content("see pdf")
            msg.add_attachment(b"%PDF-1.4 x", maintype="application", subtype="pdf", filename="e-invoice.pdf")
            payload = msg.as_bytes()
            meta = f"99 (UID 99 BODY[] {{{len(payload)}}}".encode("ascii")
            return "OK", [(meta, payload)]
        raise AssertionError(command)

    def search(self, charset, *criteria):
        return "OK", [b""]

    def close(self):
        return "OK", [b""]

    def logout(self):
        self.logged_out = True
        return "BYE", [b""]


def test_search_from_thndr_uses_all_mail(monkeypatch):
    fake = FakeUidImap()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port: fake)
    reader = GmailReader("you@gmail.com", "good")
    with reader:
        mailbox = reader.prefer_all_mail()
        query, uids = reader.search_gmail_uids(
            ["from:thndr", "subject:thndr", "thndr"],
            fallback_from="thndr",
        )
        rows = reader.peek_headers(uids[-3:], full=True)
    assert mailbox == "[Gmail]/All Mail"
    assert fake.selected == "[Gmail]/All Mail"
    assert uids == ["99"]
    assert query == "from:thndr"
    assert rows[0].subject == "Your Thndr Invoice"


def test_list_pdf_attachments_uses_uid_fetch(monkeypatch):
    fake = FakeUidImap()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port: fake)
    reader = GmailReader("you@gmail.com", "good")
    with reader:
        rows = reader.list_pdf_attachments(gmail_query="from:thndr.app filename:pdf", limit=3)
    assert fake.selected == "[Gmail]/All Mail"
    assert len(rows) == 1
    assert rows[0].filename == "e-invoice.pdf"
    assert rows[0].uid == "99"
    assert b"%PDF" in rows[0].data
