"""Faithful port of imessage-database `util/streamtyped.rs` parse().

This is the upstream *legacy* plain-text fallback, not a typedstream
object-graph decoder. Prefer the Rust helper (crabstep) when available.
"""

from __future__ import annotations

START_PATTERN = bytes((0x01, 0x2B))
END_PATTERN = bytes((0x86, 0x84))


class StreamTypedError(ValueError):
    pass


def parse_streamtyped(blob: bytes) -> str:
    start = blob.find(START_PATTERN)
    if start < 0:
        raise StreamTypedError("NoStartPattern")
    rest = blob[start + len(START_PATTERN) :]

    end = rest.find(END_PATTERN)
    if end < 0:
        raise StreamTypedError("NoEndPattern")
    payload = rest[:end]

    try:
        text = payload.decode("utf-8")
        return _drop_chars(text, 1)
    except UnicodeDecodeError:
        text = payload.decode("utf-8", errors="replace")
        return _drop_chars(text, 3)


def _drop_chars(string: str, offset: int) -> str:
    chars = list(string)
    if len(chars) <= offset:
        raise StreamTypedError("InvalidPrefix")
    return "".join(chars[offset:]).strip()
