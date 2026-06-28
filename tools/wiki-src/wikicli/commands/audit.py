"""`wiki audit` — scoped, model-assisted consistency checks (plan section 14).

Audit is the non-deterministic layer that complements `lint`. Where lint makes
deterministic structural checks that can fail a commit, audit performs scoped
semantic checks (contradiction detection, claim/source drift, coverage gaps)
and records findings as REVIEW ITEMS. Audit never silently rewrites canonical
content: deterministic validation wins, audit creates reviews, and a human or
agent applies a resolution via `wiki reviews resolve`.

Scope flags keep audits cheap and incremental:
  --changed-since <operation-id>   audit only what changed since that commit
  --topic <page-id>                audit a single page and its neighbourhood
  --source <source-id>             audit claims citing a source
  --full                           audit the whole corpus (expensive)

The MVP implements the deterministic, model-free findings that are
nevertheless review-worthy rather than commit-blocking (e.g. a synthesis whose
supporting sources have drifted in status, claims with weak/aging support,
potential duplicate syntheses). A model-backed adapter can extend this set; the
review records it produces are identical in shape.
"""

from __future__ import annotations

from ..core.claims import extract_claims
from ..core.context import Context
from ..core.derived import build_claim_index
from ..core.events import EV_REVIEW_OPENED, EventLog
from ..core.locking import EXCLUSIVE, repository_lock
from ..core.reviews import ReviewStore, SEV_ADVISORY, SEV_WARNING
from ..core.sources import parse_source
from ..core.validators import collect_all_pages
from ..errors import UsageError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("audit", help="Run scoped consistency checks, creating review items.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--changed-since", dest="changed_since", help="Operation id to audit changes since.")
    g.add_argument("--topic", help="Page id to audit.")
    g.add_argument("--source", dest="source_id", help="Source id to audit.")
    g.add_argument("--full", action="store_true", help="Audit the whole corpus.")
    p.add_argument("--wait", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo

    if not any([args.changed_since, args.topic, args.source_id, args.full]):
        raise UsageError("audit needs a scope: --changed-since | --topic | --source | --full")

    with repository_lock(repo.lock_file, repo.lock_meta_file, EXCLUSIVE,
                         wait_seconds=args.wait, command="wiki audit"):
        log = EventLog(repo.events)
        pages = collect_all_pages(repo)
        claim_index = build_claim_index(repo, pages)
        source_status = _source_status(repo)
        store = ReviewStore(repo)

        in_scope = _scope_pages(repo, pages, args, log, claim_index)

        findings = []
        findings += _drifted_support(in_scope, claim_index, source_status)
        findings += _weak_support(in_scope, claim_index, source_status)
        findings += _possible_duplicates(in_scope)

        created_seq = log.max_seq()
        opened = []
        for f in findings:
            review = store.create(
                severity=f["severity"],
                scope=f["scope"],
                reason=f["reason"],
                created_seq=created_seq,
                kind="audit",
                stale_after_operations=ctx.default_stale_after,
                extra={"finding": f["code"]},
            )
            opened.append({"review_id": review.review_id, "reason": f["reason"],
                           "severity": f["severity"]})
            log.append(EV_REVIEW_OPENED, operation_id="op-audit",
                       review_id=review.review_id, scope=f["scope"], kind="audit")

    if args.json:
        emit({"ok": True, "reviews_opened": opened, "finding_count": len(opened)}, as_json=True)
    else:
        if not opened:
            info("Audit found nothing review-worthy in scope.")
        for o in opened:
            info(f"  [{o['severity']}] {o['review_id']}: {o['reason']}")
        info(f"\n{len(opened)} review item(s) opened.")
    return 0


def _scope_pages(repo, pages, args, log: EventLog, claim_index):
    if args.full:
        return pages
    if args.topic:
        return [p for p in pages if p.id == args.topic]
    if args.source_id:
        claim_ids = set(claim_index["source_to_claims"].get(args.source_id, []))
        return [p for p in pages
                if any(c.id in claim_ids for c in extract_claims(p.body))]
    if args.changed_since:
        commit_seq = log.commit_seq_for_operation(args.changed_since)
        if commit_seq is None:
            raise UsageError(f"no committed operation {args.changed_since}")
        changed_paths = set()
        for e in log.events_after_seq(commit_seq - 1):
            for f in e.get("files_changed", []) or []:
                changed_paths.add(f)
        return [p for p in pages if repo.rel(p.path) in changed_paths]
    return pages


def _source_status(repo) -> dict:
    out = {}
    if repo.sources.is_dir():
        for sp in repo.sources.glob("*.md"):
            try:
                s = parse_source(sp)
            except Exception:
                continue
            if s.source_id:
                out[s.source_id] = s.status
    return out


def _drifted_support(pages, claim_index, source_status):
    """Stable/active syntheses whose supporting sources are no longer active."""
    findings = []
    for page in pages:
        if page.type != "synthesis":
            continue
        if page.status not in ("stable", "active"):
            continue
        for claim in extract_claims(page.body):
            inactive = [s for s in claim.sources
                        if source_status.get(s.split("#", 1)[0]) not in (None, "active")]
            if inactive and len(inactive) == len(claim.sources):
                findings.append({
                    "code": "support-drift",
                    "severity": SEV_WARNING,
                    "scope": [claim.id, page.id or ""],
                    "reason": f"claim {claim.id} on stable synthesis relies only on inactive sources",
                })
    return findings


def _weak_support(pages, claim_index, source_status):
    """Supported claims backed by a single source — advisory."""
    findings = []
    for page in pages:
        for claim in extract_claims(page.body):
            if claim.status == "supported" and len(claim.sources) == 1:
                findings.append({
                    "code": "single-source",
                    "severity": SEV_ADVISORY,
                    "scope": [claim.id],
                    "reason": f"claim {claim.id} is supported by a single source",
                })
    return findings


def _possible_duplicates(pages):
    """Syntheses with very similar titles — advisory."""
    findings = []
    seen: dict[str, str] = {}
    for page in pages:
        if page.type != "synthesis":
            continue
        title = (page.frontmatter.get("title") or "").strip().lower()
        if not title:
            continue
        if title in seen and seen[title] != page.id:
            findings.append({
                "code": "possible-duplicate",
                "severity": SEV_ADVISORY,
                "scope": [page.id or "", seen[title]],
                "reason": f"synthesis '{title}' duplicates {seen[title]}",
            })
        else:
            seen[title] = page.id or ""
    return findings
