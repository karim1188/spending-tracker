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
    assert cat.categorize(None, "fee") == "Fees"
    assert cat.categorize("UNKNOWN MERCHANT XYZ") == "Other"


def test_categorizer_extra_rules_replaceable():
    cat = Categorizer(extra_rules={"LOCALCAFE": "Food & Dining"})
    assert cat.categorize("LocalCafe Downtown") == "Food & Dining"
