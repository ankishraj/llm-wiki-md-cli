"""Hashing utilities and content-addressed storage helpers.

All canonical files and raw sources are identified by SHA-256. Page hashes
let the recovery state machine classify whether a file is in its before- or
after- state, and let lint detect tampering / stale derived state.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1024 * 1024  # 1 MiB


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_text(text: str) -> str:
    """Hash text content. Always normalised to UTF-8 with LF line endings so
    that the same logical content hashes identically across platforms."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_file_text(path: Path) -> str:
    """Hash a text file using the normalised text rule (LF, UTF-8)."""
    return hash_text(Path(path).read_text(encoding="utf-8"))


def short(sha: str, n: int = 12) -> str:
    return sha[:n]
