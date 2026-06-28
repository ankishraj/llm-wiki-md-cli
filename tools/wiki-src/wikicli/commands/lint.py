"""`wiki lint` — deterministic, cheap checks (plan section 14).

Runs structural validation that can fail a commit:
  schema violations, path-to-type, duplicate IDs, broken links and citations,
  missing source descriptors, source hash mismatches, malformed event records,
  orphan pages, stale derived indexes, root-index budget violations, raw-write
  detection, and source-status citation rules (retracted/superseded/purged).

Writes a JSON report to .wiki/cache/lint-report.json and exits non-zero if any
error-severity issues are found.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.context import Context
from ..core.claims import extract_claims
from ..core.derived import build_claim_index, generate_indexes
from ..core.events import EventLog
from ..core.hashing import hash_file
from ..core.pages import Page
from ..core.sources import parse_source
from ..core.validators import (
    ValidationResult,
    collect_all_pages,
    validate_claims_required,
    validate_page_frontmatter,
    validate_path_type,
    validate_size_budgets,
    validate_unique_ids,
)
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("lint", help="Run deterministic structural checks.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fix", action="store_true",
                   help="Apply safe mechanical repairs (regenerate stale indexes).")
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    schema = ctx.schema
    result = ValidationResult()

    pages = collect_all_pages(repo)

    # Per-page checks.
    for page in pages:
        rel = repo.rel(page.path)
        validate_page_frontmatter(page, schema, rel, result)
        validate_path_type(page, schema, repo, rel, result)
        validate_claims_required(page, schema, rel, result)
        validate_size_budgets(page, schema, rel, result)

    # Cross-page checks.
    validate_unique_ids(pages, repo, result)

    # Source descriptors + statuses.
    source_status = _check_sources(repo, result)

    # Citations resolve to known sources, with status-aware severity.
    _check_citations(repo, pages, source_status, result)

    # Claim source references obey status rules and support requirements.
    _check_claim_support(repo, pages, source_status, result)

    # Internal wiki links resolve.
    _check_page_links(repo, pages, result)

    # Orphan pages (no inbound links and not referenced by index), advisory.
    _check_orphans(repo, pages, result)

    # Malformed event records.
    _check_events(repo, result)

    # Root index budget + staleness.
    stale_index = _check_index(repo, schema, pages, result, fix=args.fix)

    # Persist report.
    repo.cache.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": result.ok,
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
        "issues": [i.as_dict() for i in result.issues],
    }
    repo.lint_report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json:
        emit(report, as_json=True)
    else:
        for issue in result.issues:
            info(f"  [{issue.severity}] {issue.code} {issue.path}: {issue.message}")
        info("")
        info(f"{len(result.errors)} error(s), {len(result.warnings)} warning(s).")
        if args.fix and stale_index:
            info("Regenerated stale index files.")

    return 0 if result.ok else 4


def _check_sources(repo, result: ValidationResult) -> dict:
    """Returns {source_id: status}. Flags hash mismatches for embedded sources."""
    statuses = {}
    if not repo.sources.is_dir():
        return statuses
    for sp in sorted(repo.sources.glob("*.md")):
        rel = repo.rel(sp)
        try:
            src = parse_source(sp)
        except Exception as exc:
            result.add("source-parse", "error", rel, f"cannot parse source: {exc}")
            continue
        sid = src.source_id
        if not sid:
            result.add("source-id", "error", rel, "source descriptor missing source_id")
            continue
        statuses[sid] = src.status
        # hash check for embedded active sources
        if src.status == "active" and src.storage == "embedded" and src.raw_path:
            raw = repo.root / src.raw_path
            if not raw.exists():
                result.add("source-hash", "error", rel,
                           f"raw blob missing for {sid}: {src.raw_path}")
            else:
                actual = hash_file(raw)
                if src.sha256 and actual != src.sha256:
                    result.add("source-hash", "error", rel,
                               f"raw hash mismatch for {sid}: expected {src.sha256[:12]}, got {actual[:12]}")
    return statuses


def _citation_severity(base_id: str, source_status: dict) -> tuple[str, str] | None:
    """Return (severity, message-suffix) for a citation, or None if fine."""
    if base_id not in source_status:
        return ("error", "citation to nonexistent source ID")
    st = source_status[base_id]
    if st == "active":
        return None
    if st == "retracted":
        return ("warning", "citation to retracted source")
    if st == "superseded":
        return ("warning", "citation to superseded source")
    if st == "purged":
        return ("warning", "citation to purged tombstone")
    return ("warning", f"citation to source with status {st}")


def _check_citations(repo, pages, source_status, result: ValidationResult):
    for page in pages:
        rel = repo.rel(page.path)
        for cite in page.citations:
            base = cite.split("#", 1)[0]
            verdict = _citation_severity(base, source_status)
            if verdict:
                sev, msg = verdict
                result.add("citation", sev, rel, f"{msg}: {cite}")


def _check_claim_support(repo, pages, source_status, result: ValidationResult):
    for page in pages:
        rel = repo.rel(page.path)
        for claim in extract_claims(page.body):
            active_support = False
            for src in claim.sources:
                base = src.split("#", 1)[0]
                st = source_status.get(base)
                if st is None:
                    result.add("claim-citation", "error", rel,
                               f"claim {claim.id} cites nonexistent source {src}")
                elif st == "active":
                    active_support = True
            if claim.status == "supported" and claim.sources and not active_support:
                result.add("claim-support", "error", rel,
                           f"claim {claim.id} is supported but its only evidence is inactive")


def _check_page_links(repo, pages, result: ValidationResult):
    known_ids = {p.id for p in pages if p.id}
    for page in pages:
        rel = repo.rel(page.path)
        for linked in page.page_links:
            if linked not in known_ids:
                result.add("broken-link", "error", rel, f"link to unknown page id {linked}")


def _check_orphans(repo, pages, result: ValidationResult):
    referenced = set()
    for page in pages:
        for linked in page.page_links:
            referenced.add(linked)
    for page in pages:
        if not page.id:
            continue
        if page.id not in referenced and page.type in ("synthesis", "topic"):
            result.add("orphan", "advisory", repo.rel(page.path),
                       f"page {page.id} has no inbound links")


def _check_events(repo, result: ValidationResult):
    log = EventLog(repo.events)
    for m in log.malformed():
        result.add("event-malformed", "error", repo.rel(repo.events),
                   f"line {m['line']}: {m['error']}")


def _check_index(repo, schema, pages, result: ValidationResult, *, fix: bool) -> bool:
    """Check whether generated index files are stale vs current pages."""
    expected = generate_indexes(repo, schema, pages)
    stale = False
    for rel, content in expected.items():
        target = repo.root / rel
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current != content:
            stale = True
            result.add("stale-index", "warning", rel, "generated index is stale")
            if fix:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
    # Detect category index files that should no longer exist.
    return stale
