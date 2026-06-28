"""Source descriptors: canonical provenance (plan sections 8, 10, 13).

A source descriptor is a Markdown file under wiki/sources/<source-id>.md whose
frontmatter records identity, hash, size, evidence class, storage mode and
lifecycle status (active / retracted / superseded / purged). The descriptor is
canonical knowledge; the raw blob it points at is content-addressed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .pages import build_page_text, parse_page, parse_frontmatter

SOURCE_ID_RE = re.compile(r"^source-[a-z0-9]+(?:-[a-z0-9]+)*$")

EVIDENCE_CLASSES = (
    "canonical-project-artifact",
    "primary",
    "secondary",
    "tertiary",
    "generated",
    "unknown",
)

# Precedence order (lower index = higher precedence). Used for review priority
# and recommendations, never for silent deletion of conflicting claims.
EVIDENCE_PRECEDENCE = {cls: i for i, cls in enumerate(EVIDENCE_CLASSES)}

SOURCE_STATUSES = ("active", "retracted", "superseded", "purged")

STORAGE_MODES = ("embedded", "external")


@dataclass
class Source:
    path: Path
    frontmatter: dict
    body: str

    @property
    def source_id(self) -> str | None:
        return self.frontmatter.get("source_id") or self.frontmatter.get("id")

    @property
    def status(self) -> str:
        return self.frontmatter.get("status", "active")

    @property
    def sha256(self) -> str | None:
        return self.frontmatter.get("sha256") or self.frontmatter.get("former_sha256")

    @property
    def storage(self) -> str:
        return self.frontmatter.get("storage", "embedded")

    @property
    def raw_path(self) -> str | None:
        return self.frontmatter.get("raw_path")

    @property
    def evidence_class(self) -> str:
        return self.frontmatter.get("evidence_class", "unknown")

    @property
    def classification_status(self) -> str:
        return self.frontmatter.get("classification_status", "proposed")

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_tombstone(self) -> bool:
        return self.status == "purged"


def parse_source(path: Path) -> Source:
    page = parse_page(path)
    return Source(path=Path(path), frontmatter=page.frontmatter, body=page.body)


def build_source_descriptor(
    *,
    source_id: str,
    sha256: str,
    size_bytes: int,
    storage: str,
    raw_path: str | None = None,
    uri: str | None = None,
    evidence_class: str = "unknown",
    classification_status: str = "proposed",
    status: str = "active",
    title: str | None = None,
    retrieval_hint: str | None = None,
    summary: str | None = None,
    ext: str | None = None,
) -> str:
    fm: dict = {
        "source_id": source_id,
        "status": status,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "storage": storage,
        "evidence_class": evidence_class,
        "classification_status": classification_status,
    }
    if title:
        fm["title"] = title
    if ext:
        fm["ext"] = ext
    if storage == "embedded" and raw_path:
        fm["raw_path"] = raw_path
    if storage == "external":
        if uri:
            fm["uri"] = uri
        if retrieval_hint:
            fm["retrieval_hint"] = retrieval_hint
    body = summary or f"Source descriptor for `{source_id}`."
    return build_page_text(fm, body)


def build_tombstone(
    *,
    source_id: str,
    former_sha256: str,
    former_size_bytes: int,
    purged_at: str,
    reason: str,
    replacement_source_id: str | None = None,
) -> str:
    fm = {
        "source_id": source_id,
        "status": "purged",
        "former_sha256": former_sha256,
        "former_size_bytes": former_size_bytes,
        "purged_at": purged_at,
        "reason": reason,
        "replacement_source_id": replacement_source_id,
    }
    body = (
        f"Tombstone for purged source `{source_id}`. The raw blob has been "
        f"removed but this identity remains resolvable.\n\nReason: {reason}"
    )
    return build_page_text(fm, body)
