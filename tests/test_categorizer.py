from __future__ import annotations

from categorizer.categorizer import Categorizer
from parsers.bank_detector import BankDetector
from tests.helpers import make_bank_registry
from tests.test_parsers import _msg


def test_bank_detection_by_configured_sender():
    registry = make_bank_registry(SNB=("SNB",), AlRajhi=("AlRajhi",))
    detector = BankDetector(registry)
    assert detector.is_bank_sender("SNB")
    assert detector.is_bank_sender("snb")
    assert not detector.is_bank_sender("Amazon")
    parser = detector.detect(_msg("SNB", "شراء 10.00 SAR"))
    assert parser is not None
    assert parser.bank_name == "SNB"
    assert detector.detect(_msg("Amazon", "شراء 10.00 SAR")) is None


def test_snb_alahli_and_mobily_pay_senders():
    registry = make_bank_registry(SNB=("SNB-AlAhli",), MobilyPay=("Mobily Pay",))
    detector = BankDetector(registry)
    assert detector.is_bank_sender("SNB-AlAhli")
    assert detector.is_bank_sender("SNB-AlAhli.")
    assert detector.is_bank_sender("Mobily Pay")
    snb = detector.detect(_msg("SNB-AlAhli", "شراء بمبلغ 20.00 SAR من HungerStation"))
    assert snb is not None and snb.bank_name == "SNB"
    mobily = detector.detect(_msg("Mobily Pay", "Purchase 15.50 SAR at Jahez"))
    assert mobily is not None and mobily.bank_name == "MobilyPay"


def test_categorizer_merchant_rules():
    cat = Categorizer()
    assert cat.categorize("HungerStation") == "Food & Dining"
    assert cat.categorize("JAHEZ Riyadh") == "Food & Dining"
    assert cat.categorize("Uber trip") == "Transportation"
    assert cat.categorize("Careem") == "Transportation"
    assert cat.categorize("Amazon.sa") == "Shopping"


def test_categorizer_type_fallback_and_other():
    cat = Categorizer()
    assert cat.categorize(None, "salary") == "Salary"
    assert cat.categorize(None, "bank_transfer_in") == "Transfers"
    assert cat.categorize(None, "fee") == "Fees"
    assert cat.categorize("UNKNOWN MERCHANT XYZ") == "Other"


def test_merchant_rule_beats_sender():
    cat = Categorizer(extra_rules={"HUNGERSTATION": "Groceries"})
    assert cat.categorize("HungerStation", "card_purchase") == "Groceries"


def test_categorizer_extra_rules_replaceable():
    cat = Categorizer(extra_rules={"LOCALCAFE": "Food & Dining"})
    assert cat.categorize("LocalCafe Downtown") == "Food & Dining"
