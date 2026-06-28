"""`wiki retract <source-id>` — default source retraction (plan section 13).

Preserves the raw source, sets descriptor status to retracted, finds claims
that cite it, and opens review items for claims whose only active support is
lost. Synthesis pages are rebuilt only after approval (i.e. the agent resolves
the reviews), never automatically.
"""

from __future__ import annotations

from ..core.context import Context
from ..core.derived import build_claim_index
from ..core.events import EV_SOURCE_RETRACTED, EV_OPERATION_COMMITTED, EV_REVIEW_OPENED
from ..core.operations import Operation
from ..core.pages import build_page_text
from ..core.reviews import ReviewStore, SEV_BLOCKING
from ..core.session import writer_session
from ..core.sources import parse_source
from ..core.validators import collect_all_pages
from ..errors import UsageError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("retract", help="Retract a source (default deletion mode).")
    p.add_argument("source_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--wait", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    sid = args.source_id
    descriptor = repo.sources / f"{sid}.md"
    if not descriptor.exists():
        raise UsageError(f"source not found: {sid}")

    with writer_session(ctx, f"wiki retract {sid}", wait_seconds=args.wait) as log:
        src = parse_source(descriptor)
        if src.status == "retracted":
            info(f"{sid} is already retracted.")
            return 0

        fm = dict(src.frontmatter)
        fm["status"] = "retracted"
        fm["retracted_reason"] = args.reason
        new_text = build_page_text(fm, src.body)

        op = Operation.create(repo, "retract", {"source_id": sid, "reason": args.reason})
        op.stage_write(repo.rel(descriptor), new_text)
        op.prepare()
        op.apply()

        # Find affected claims: those citing this source whose remaining
        # support is now all-inactive.
        pages = collect_all_pages(repo)
        claim_index = build_claim_index(repo, pages)
        affected = claim_index["source_to_claims"].get(sid, [])

        commit_seq = log.next_seq()  # the commit event will take this seq
        events = [
            {"operation_id": op.operation_id, "type": EV_SOURCE_RETRACTED,
             "source_id": sid, "reason": args.reason, "affected_claims": affected},
            {"operation_id": op.operation_id, "type": EV_OPERATION_COMMITTED,
             "files_changed": op.changed_paths(), "source_id": sid,
             "affected_claims": affected},
        ]
        written = log.append_many(events)
        committed_seq = next(e["seq"] for e in written if e["type"] == EV_OPERATION_COMMITTED)
        op.mark_committed()

        # Open blocking reviews for claims that lost their sole active support.
        store = ReviewStore(repo)
        opened = []
        active_sources = _active_source_ids(repo)
        for claim_id in affected:
            srcs = claim_index["claim_to_sources"].get(claim_id, [])
            remaining_active = [s for s in srcs if s.split("#", 1)[0] in active_sources
                                and s.split("#", 1)[0] != sid]
            if not remaining_active:
                review = store.create(
                    severity=SEV_BLOCKING,
                    scope=[claim_id, sid],
                    reason=f"sole supporting source {sid} retracted",
                    created_seq=committed_seq,
                    kind="retraction",
                    stale_after_operations=ctx.default_stale_after,
                )
                opened.append(review.review_id)
                log.append(EV_REVIEW_OPENED, operation_id=op.operation_id,
                           review_id=review.review_id, scope=[claim_id, sid])

    if args.json:
        emit({"ok": True, "source_id": sid, "affected_claims": affected,
              "reviews_opened": opened}, as_json=True)
    else:
        info(f"Retracted {sid}. {len(affected)} claim(s) affected, {len(opened)} review(s) opened.")
        info("  raw source preserved. Run `wiki rebuild` to refresh indexes.")
    return 0


def _active_source_ids(repo) -> set[str]:
    out = set()
    if repo.sources.is_dir():
        for sp in repo.sources.glob("*.md"):
            try:
                s = parse_source(sp)
            except Exception:
                continue
            if s.status == "active" and s.source_id:
                out.add(s.source_id)
    return out
