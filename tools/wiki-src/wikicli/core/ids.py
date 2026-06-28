"""Sortable identifiers (ULID-style) and timestamp helpers.

operation_id and event_id are ULID-style: a 48-bit millisecond timestamp
followed by 80 bits of randomness, Crockford base32 encoded. They are
lexicographically sortable by creation time, but ordering of events is
authoritatively determined by the monotonic `seq` integer, not by these IDs.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

# Crockford base32 alphabet (excludes I, L, O, U to avoid ambiguity).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def new_ulid(prefix: str = "") -> str:
    """Generate a ULID-style identifier. `prefix` is prepended verbatim
    (e.g. 'op-', 'review-' callers handle their own prefixes)."""
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits
    ts_part = _encode(ms, 10)
    rand_part = _encode(rand, 16)
    return f"{prefix}{ts_part}{rand_part}"


def now_iso() -> str:
    """Current UTC time in ISO 8601 with second precision and Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
