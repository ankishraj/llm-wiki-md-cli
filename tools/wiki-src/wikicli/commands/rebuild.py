"""`wiki rebuild` — regenerate all derived state.

Derived state (indexes, manifest, backlinks, claim index, lint report) is
always rebuildable from canonical sources, pages, claims and the event log.
This command runs under the exclusive lock and commits regenerated indexes
through an operation so generation participates in the journal.
"""

from __future__ import annotations

from ..core.context import Context
from ..core.derived import generate_indexes, write_caches
from ..core.events import EV_DERIVED_REBUILT, EventLog
from ..core.operations import Operation
from ..core.session import writer_session
from ..core.validators import collect_all_pages
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("rebuild", help="Regenerate derived indexes and caches.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--wait", type=float, default=0.0)
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    with writer_session(ctx, "wiki rebuild", wait_seconds=args.wait) as log:
        pages = collect_all_pages(repo)
        op = Operation.create(repo, "rebuild", {})
        outputs = generate_indexes(repo, ctx.schema, pages)
        # Remove any stale category indexes no longer in outputs.
        _stage_index_changes(repo, op, outputs)
        op.prepare()
        op.apply()
        # Non-canonical caches are written directly (not journalled).
        write_caches(repo, pages)
        log.append(EV_DERIVED_REBUILT, operation_id=op.operation_id,
                   files_changed=op.changed_paths())
        op.mark_committed()
    if args.json:
        emit({"ok": True, "regenerated": list(outputs.keys())}, as_json=True)
    else:
        info(f"Rebuilt derived state ({len(outputs)} index file(s)).")
    return 0


def _stage_index_changes(repo, op, outputs):
    # Stage writes for all expected outputs that differ.
    for rel, content in outputs.items():
        target = repo.root / rel
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current != content:
            op.stage_write(rel, content)
    # Delete category indexes that exist but are no longer expected.
    for cat_index in repo.pages.rglob("_index.md"):
        rel = repo.rel(cat_index)
        if rel not in outputs:
            op.stage_delete(rel)
