from __future__ import annotations

from datetime import datetime, timezone

from models.message import Message
from parsers.banks.alrajhi import AlRajhiParser
from parsers.banks.alinma import AlinmaParser
from parsers.banks.riyad import RiyadParser
from parsers.banks.sab import SabParser
from parsers.banks.snb import SnbParser
from parsers.generic import parse_amount
from tests.helpers import make_bank_registry


def _msg(sender: str, text: str, guid: str = "guid-1") -> Message:
    return Message(
        id=84024,
        guid=guid,
        sender=sender,
        text=text,
        timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        service="SMS",
        is_from_me=False,
    )


def test_snb_card_purchase():
    registry = make_bank_registry(SNB=("SNB",))
    parser = SnbParser(registry)
    message = _msg(
        "SNB",
        "شراء بمبلغ 74.50 SAR من HungerStation بطاقة *1234",
    )
    assert parser.can_parse(message)
    tx = parser.parse(message)
    assert tx is not None
    assert tx.amount == 74.50
    assert tx.currency == "SAR"
    assert tx.transaction_type == "card_purchase"
    assert tx.merchant == "HungerStation"
    assert tx.card_last4 == "1234"
    assert tx.bank == "SNB"


def test_sar_currency_aliases():
    amount, currency = parse_amount("خصم 20.00 ر.س")
    assert amount == 20.0
    assert currency == "SAR"
    amount, currency = parse_amount("SAR 15.5")
    assert amount == 15.5
    assert currency == "SAR"
    amount, currency = parse_amount("المبلغ 1,234.00 ريال")
    assert amount == 1234.0
    assert currency == "SAR"


def test_amount_parsing_without_inventing():
    amount, currency = parse_amount("hello there")
    assert amount is None
    assert currency is None


def test_alrajhi_online_purchase():
    registry = make_bank_registry(AlRajhi=("AlRajhi",))
    parser = AlRajhiParser(registry)
    tx = parser.parse(_msg("AlRajhi", "عملية أونلاين بمبلغ 99.00 SAR من Amazon بطاقة *8899"))
    assert tx is not None
    assert tx.transaction_type == "online_purchase"
    assert tx.amount == 99.0
    assert tx.merchant == "Amazon"


def test_riyad_apple_pay():
    registry = make_bank_registry(RiyadBank=("RiyadBank",))
    parser = RiyadParser(registry)
    tx = parser.parse(_msg("RiyadBank", "Apple Pay purchase 12.00 SAR at CAREEM card *4321"))
    assert tx is not None
    assert tx.transaction_type == "apple_pay"
    assert tx.merchant == "CAREEM"


def test_sab_transfer_out():
    registry = make_bank_registry(SAB=("SAB",))
    parser = SabParser(registry)
    tx = parser.parse(_msg("SAB", "حوالة صادرة بمبلغ 500 SAR إلى حساب *7788"))
    assert tx is not None
    assert tx.transaction_type == "bank_transfer_out"
    assert tx.amount == 500
    assert tx.account_last4 == "7788"


def test_alinma_salary():
    registry = make_bank_registry(Alinma=("Alinma",))
    parser = AlinmaParser(registry)
    tx = parser.parse(_msg("Alinma", "راتب بمبلغ 12000.00 SAR رصيد 15000.00"))
    assert tx is not None
    assert tx.transaction_type == "salary"
    assert tx.amount == 12000.0
    assert tx.balance == 15000.0


def test_snb_incoming_salary_transfer():
    registry = make_bank_registry(SNB=("SNB-AlAhli",))
    parser = SnbParser(registry)
    tx = parser.parse(_msg("SNB-AlAhli", "حوالة واردة راتب\nمبلغ SAR 10000"))
    assert tx is not None
    assert tx.transaction_type == "salary"
    assert tx.amount == 10000.0
    incoming = parser.parse(_msg("SNB-AlAhli", "حوالة واردة بمبلغ 500 SAR"))
    assert incoming is not None
    assert incoming.transaction_type == "bank_transfer_in"


def test_unknown_when_confidence_low():
    registry = make_bank_registry(SNB=("SNB",))
    parser = SnbParser(registry)
    tx = parser.parse(_msg("SNB", "تنبيه: تم تحديث بيانات التواصل"))
    assert tx is None


def test_wrong_sender_rejected():
    registry = make_bank_registry(SNB=("SNB",))
    parser = SnbParser(registry)
    message = _msg("Amazon", "شراء بمبلغ 74.50 SAR من HungerStation بطاقة *1234")
    assert parser.can_parse(message) is False
    assert parser.parse(message) is None


def test_snb_alahli_sender_parses():
    registry = make_bank_registry(SNB=("SNB-AlAhli",))
    parser = SnbParser(registry)
    message = _msg("SNB-AlAhli", "شراء بمبلغ 74.50 SAR من HungerStation بطاقة *1234")
    assert parser.can_parse(message)
    tx = parser.parse(message)
    assert tx is not None
    assert tx.bank == "SNB"
    assert tx.amount == 74.50


def test_mobily_pay_purchase():
    from parsers.banks.mobily import MobilyPayParser

    registry = make_bank_registry(MobilyPay=("Mobily Pay",))
    parser = MobilyPayParser(registry)
    message = _msg("Mobily Pay", "Purchase 32.00 SAR at HungerStation")
    assert parser.can_parse(message)
    tx = parser.parse(message)
    assert tx is not None
    assert tx.bank == "MobilyPay"
    assert tx.amount == 32.0
    assert tx.currency == "SAR"
    assert tx.merchant == "HungerStation"


def test_snb_mobily_topup_is_not_double_counted():
    registry = make_bank_registry(SNB=("SNB-AlAhli",), MobilyPay=("Mobily Pay",))
    snb = SnbParser(registry)
    topup = snb.parse(
        _msg(
            "SNB-AlAhli",
            "تحويل إلى Mobily Pay بمبلغ 200.00 SAR",
        )
    )
    assert topup is not None
    assert topup.transaction_type == "wallet_topup"

    from parsers.banks.mobily import MobilyPayParser

    mobily = MobilyPayParser(registry)
    purchase = mobily.parse(_msg("Mobily Pay", "Purchase 32.00 SAR at HungerStation"))
    assert purchase is not None
    assert purchase.transaction_type == "card_purchase"
    credit = mobily.parse(_msg("Mobily Pay", "Wallet top up 200.00 SAR received"))
    assert credit is not None
    assert credit.transaction_type == "wallet_topup"


def test_snb_activation_pin_is_not_a_transaction():
    registry = make_bank_registry(SNB=("SNB-AlAhli",))
    parser = SnbParser(registry)
    message = _msg(
        "SNB-AlAhli",
        "لا تشارك رمز التفعيل 1093\nتحويل لبنك محلي\nمبلغ SAR 1000",
        guid="781A1E6A-0B82-B291-7EEB-ED6DDC8E2788",
    )
    assert parser.parse(message) is None


def test_committed_banks_json_has_user_senders():
    from config.loader import BankRegistry

    registry = BankRegistry.load()
    assert registry.bank_for_sender("SNB-AlAhli") == "SNB"
    assert registry.bank_for_sender("Mobily Pay") == "MobilyPay"

