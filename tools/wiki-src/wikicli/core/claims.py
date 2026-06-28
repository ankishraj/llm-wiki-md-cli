"""Claim block parsing (plan section 9, pinned format).

Claim blocks use a fenced, language-tagged block (NOT HTML comments), so they
are visible to Markdown renderers, linters and ripgrep, survive rendering
predictably, and are greppable. Canonical form:

    ```claim
    id: claim-auth-001
    status: supported
    sources:
      - source-rfc-example#section-4
      - source-design-review#page-12
    ```
    The service uses short-lived access tokens and rotating refresh tokens.
    ```/claim```

The fenced `claim` block holds structured YAML metadata; the prose that
immediately follows, up to the `` ```/claim``` `` close marker, is the
canonical claim text.

Claim blocks are REQUIRED for synthesis and decision pages, disputed claims,
and claims affected by retraction/supersession.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .hashing import hash_text
from .pages import parse_frontmatter

# Opening fence: ```claim  (allow surrounding whitespace, optional info trailing)
_OPEN_RE = re.compile(r"^```claim[ \t]*$", re.MULTILINE)
# Closing marker for the metadata fence is a bare ```; the block then ends at
# ```/claim```. We parse manually to keep the prose between the two.

CLAIM_ID_RE = re.compile(r"^claim-[a-z0-9]+(?:-[a-z0-9]+)*$")
VALID_CLAIM_STATUS = ("supported", "disputed", "unsupported", "superseded", "draft")


@dataclass
class Claim:
    id: str
    status: str
    sources: list[str]
    text: str
    line: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hash_text(self.text.strip())


def extract_claims(body: str) -> list[Claim]:
    """Extract all claim blocks from a page body, in document order."""
    claims: list[Claim] = []
    lines = body.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        if _OPEN_RE.match(lines[i].rstrip()):
            start_line = i + 1
            # Collect metadata until a bare ``` fence.
            meta_lines = []
            j = i + 1
            while j < n and lines[j].strip() != "```":
                meta_lines.append(lines[j])
                j += 1
            if j >= n:
                # Unterminated metadata fence; skip (lint will flag malformed).
                break
            # j is the closing ``` of metadata. Prose starts at j+1.
            prose_lines = []
            k = j + 1
            while k < n and lines[k].strip() not in ("```/claim```", "```/claim"):
                prose_lines.append(lines[k])
                k += 1
            # k is the close marker (or end).
            meta = parse_frontmatter("\n".join(meta_lines))
            claim = Claim(
                id=str(meta.get("id", "")),
                status=str(meta.get("status", "")),
                sources=[s for s in (meta.get("sources") or []) if isinstance(s, str)],
                text="\n".join(prose_lines).strip(),
                line=start_line,
                meta=meta,
            )
            claims.append(claim)
            i = k + 1
            continue
        i += 1
    return claims


def render_claim(claim: Claim) -> str:
    """Render a Claim back to canonical fenced form."""
    meta_lines = [f"id: {claim.id}", f"status: {claim.status}"]
    if claim.sources:
        meta_lines.append("sources:")
        for s in claim.sources:
            meta_lines.append(f"  - {s}")
    meta_block = "\n".join(meta_lines)
    return f"```claim\n{meta_block}\n```\n{claim.text}\n```/claim```"


def validate_claim_shape(claim: Claim) -> list[str]:
    """Deterministic structural checks for a single claim. Returns errors."""
    errors = []
    if not claim.id or not CLAIM_ID_RE.match(claim.id):
        errors.append(f"claim id invalid or missing: {claim.id!r}")
    if claim.status not in VALID_CLAIM_STATUS:
        errors.append(f"claim {claim.id}: invalid status {claim.status!r}")
    if not claim.text.strip():
        errors.append(f"claim {claim.id}: empty claim text")
    if claim.status in ("supported", "disputed") and not claim.sources:
        errors.append(f"claim {claim.id}: status {claim.status} requires at least one source")
    return errors
