"""Validators (plan sections 7, 14).

Two layers:
  * JSON Schema validation of page frontmatter (delegated to jsonschema).
  * CLI-enforced structural rules that JSON Schema cannot express:
      - path-to-type consistency
      - unique page IDs across the wiki
      - citation syntax + claim-block requirements
      - forbidden writes beneath raw/
      - index and page size budgets

These are deterministic and cheap; they belong to `wiki lint` and to the
pre-commit verify step, and can fail a commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import jsonschema_compat as jsonschema

from .claims import extract_claims, validate_claim_shape
from .pages import Page, parse_page
from .paths import Repo


@dataclass
class Issue:
    code: str
    severity: str  # "error" | "warning"
    path: str
    message: str

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)

    def add(self, code, severity, path, message):
        self.issues.append(Issue(code, severity, path, message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "ValidationResult"):
        self.issues.extend(other.issues)


def validate_page_frontmatter(page: Page, schema: dict, rel_path: str, result: ValidationResult):
    validator = jsonschema.Draft7Validator(schema)
    for err in sorted(validator.iter_errors(page.frontmatter), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<frontmatter>"
        result.add("schema", "error", rel_path, f"{loc}: {err.message}")


def validate_path_type(page: Page, schema: dict, repo: Repo, rel_path: str, result: ValidationResult):
    page_type = page.type
    type_dir = schema.get("pageTypeDir", {})
    if page_type not in type_dir:
        result.add("path-type", "error", rel_path, f"unknown page type {page_type!r}")
        return
    expected_dir = type_dir[page_type]
    actual_dir = page.path.parent.name
    if actual_dir != expected_dir:
        result.add(
            "path-type", "error", rel_path,
            f"page type {page_type!r} must live in pages/{expected_dir}/, found in {actual_dir}/",
        )


def validate_claims_required(page: Page, schema: dict, rel_path: str, result: ValidationResult):
    claim_required = set(schema.get("claimRequiredTypes", []))
    claims = extract_claims(page.body)
    if page.type in claim_required and not claims:
        result.add(
            "claim-required", "error", rel_path,
            f"page type {page.type!r} requires at least one claim block",
        )
    for c in claims:
        for err in validate_claim_shape(c):
            result.add("claim-shape", "error", rel_path, err)
    # disputed pages must mark their disputed claims
    if page.status == "disputed" and claims:
        if not any(c.status == "disputed" for c in claims):
            result.add(
                "claim-disputed", "warning", rel_path,
                "page status is disputed but no claim is marked disputed",
            )


def validate_size_budgets(page: Page, schema: dict, rel_path: str, result: ValidationResult):
    limits = schema.get("limits", {})
    max_bytes = limits.get("max_page_bytes")
    max_headings = limits.get("max_heading_count")
    size = len(page.raw_text.encode("utf-8"))
    if max_bytes and size > max_bytes:
        result.add("page-size", "error", rel_path, f"page is {size} bytes, exceeds limit {max_bytes}")
    if max_headings and len(page.headings) > max_headings:
        result.add(
            "page-headings", "error", rel_path,
            f"page has {len(page.headings)} headings, exceeds limit {max_headings}",
        )


def validate_no_raw_writes(changed_paths: list[str], result: ValidationResult):
    """Raw sources are content-addressed and immutable. A canonical change set
    must never modify files beneath wiki/raw/ except via the ingest/purge
    operations that own them. Direct edits are forbidden."""
    for p in changed_paths:
        norm = p.replace("\\", "/")
        if "/raw/sha256/" in norm or norm.endswith("wiki/raw"):
            result.add("raw-immutable", "error", p, "writes beneath wiki/raw/ are forbidden")


def collect_all_pages(repo: Repo) -> list[Page]:
    pages: list[Page] = []
    if not repo.pages.is_dir():
        return pages
    for md in sorted(repo.pages.rglob("*.md")):
        if md.name.startswith("_"):
            continue  # generated category indexes
        pages.append(parse_page(md))
    return pages


def validate_unique_ids(pages: list[Page], repo: Repo, result: ValidationResult):
    seen: dict[str, str] = {}
    for page in pages:
        pid = page.id
        if not pid:
            continue
        rel = repo.rel(page.path)
        if pid in seen:
            result.add("duplicate-id", "error", rel, f"duplicate page id {pid!r}, also in {seen[pid]}")
        else:
            seen[pid] = rel
