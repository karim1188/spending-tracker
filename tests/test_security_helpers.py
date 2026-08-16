from __future__ import annotations

from collector.macos_access import mask_sender
from collector.streamtyped import StreamTypedError, parse_streamtyped
from tests.helpers import make_streamtyped_blob


def test_streamtyped_malformed_raises():
    try:
        parse_streamtyped(b"not a typed body")
        assert False, "expected StreamTypedError"
    except StreamTypedError:
        pass


def test_streamtyped_roundtrip():
    assert parse_streamtyped(make_streamtyped_blob("abc")) == "abc"


def test_mask_phone_sender_keeps_short_codes():
    assert mask_sender("SNB") == "SNB"
    masked = mask_sender("+96651234567")
    assert masked.startswith("+9665")
    assert "123" not in masked
