"""`wiki promote <answer-file> --status draft|stable` (plan section 12).

Promotion requires explicit user intent. Draft supports sparse early-stage
projects; stable requires stronger support. The CLI enforces the mechanical
preconditions; the agent supplies the answer file with frontmatter + claims.

Draft synthesis requires: at least one valid source, no duplicate canonical id.
Stable synthesis requires one of: multiple independent supporting sources; one
canonical-project-artifact / accepted decision source; or explicit --approve
for a single authoritative source (when config allows).
"""

from __future__ import annotations

from pathlib import Path

from ..core.claims import extract_claims
from ..core.context import Context
from ..core.events import EV_PAGE_PROMOTED, EV_OPERATION_COMMITTED
from ..core.operations import Operation
from ..core.pages import build_page_text, parse_page
from ..core.session import writer_session
from ..core.sources import parse_source
from ..core.validators import collect_all_pages
from ..errors import UsageError, ValidationError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("promote", help="Promote an answer file into a synthesis page.")
    p.add_argument("answer_file")
    p.add_argument("--as", dest="as_type", default="synthesis", choices=["synthesis"])
    p.add_argument("--status", default="draft", choices=["draft", "stable"])
    p.add_argument("--approve", action="store_true",
                   help="Approve a single authoritative source as sufficient for stable.")
    p.add_argument("--wait", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    answer = Path(args.answer_file)
    if not answer.exists():
        raise UsageError(f"answer file not found: {answer}")

    page = parse_page(answer)
    pid = page.id
    if not pid:
        raise UsageError("answer file frontmatter must include an id (synthesis-<slug>).")
    if page.type != "synthesis":
        raise UsageError("promotion target must have type: synthesis.")

    claims = extract_claims(page.body)
    if not claims:
        raise ValidationError("a synthesis must contain at least one claim block.")

    # Gather sources from claims, check validity + activity.
    active_sources = _active_sources(repo)
    all_source_ids = set()
    for c in claims:
        for s in c.sources:
            all_source_ids.add(s.split("#", 1)[0])
    valid_active = [s for s in all_source_ids if s in active_sources]

    if not valid_active:
        raise ValidationError("promotion requires at least one valid, active source.")

    # Duplicate id check.
    existing_ids = {p.id for p in collect_all_pages(repo)}
    target_rel = repo.rel(repo.page_type_dir("syntheses") / f"{_slug_from_id(pid)}.md")
    target_path = repo.root / target_rel
    if pid in existing_ids and not target_path.exists():
        raise UsageError(f"page id {pid} already exists elsewhere; update it instead.")

    if args.status == "stable":
        _check_stable_preconditions(valid_active, active_sources, args.approve, ctx)

    fm = dict(page.frontmatter)
    fm["status"] = args.status
    new_text = build_page_text(fm, page.body)

    with writer_session(ctx, f"wiki promote {answer}", wait_seconds=args.wait) as log:
        op = Operation.create(repo, "promote", {"id": pid, "status": args.status})
        op.stage_write(target_rel, new_text)
        op.prepare()
        op.apply()
        log.append_many([
            {"operation_id": op.operation_id, "type": EV_PAGE_PROMOTED,
             "page_id": pid, "status": args.status, "path": target_rel},
            {"operation_id": op.operation_id, "type": EV_OPERATION_COMMITTED,
             "files_changed": op.changed_paths()},
        ])
        op.mark_committed()

    if args.json:
        emit({"ok": True, "id": pid, "status": args.status, "path": target_rel}, as_json=True)
    else:
        info(f"Promoted {pid} as {args.status} synthesis -> {target_rel}")
        info("  run `wiki rebuild` to refresh indexes.")
    return 0


def _check_stable_preconditions(valid_active, active_sources, approve, ctx):
    if len(valid_active) >= 2:
        return
    # single source: must be canonical-project-artifact / accepted decision, or
    # approved when config allows.
    only = valid_active[0]
    cls = active_sources.get(only)
    if cls in ("canonical-project-artifact",):
        return
    allow_single = ctx.config.get("promotion", {}).get(
        "allow_single_source_stable_with_approval", True)
    if approve and allow_single:
        return
    raise ValidationError(
        "stable synthesis needs multiple independent sources, a canonical "
        "project artifact, or explicit --approve for a single authoritative source.")


def _active_sources(repo) -> dict:
    out = {}
    if repo.sources.is_dir():
        for sp in repo.sources.glob("*.md"):
            try:
                s = parse_source(sp)
            except Exception:
                continue
            if s.status == "active" and s.source_id:
                out[s.source_id] = s.evidence_class
    return out


def _slug_from_id(pid: str) -> str:
    # synthesis-token-rotation -> token-rotation
    parts = pid.split("-", 1)
    return parts[1] if len(parts) == 2 else pid
