"""`wiki supersede <old> <new>` — mark one source as superseded by another
(plan section 13). The old descriptor's status becomes `superseded` and records
the replacement. Recency is decisive only via explicit supersession like this.
"""

from __future__ import annotations

from ..core.context import Context
from ..core.events import EV_SOURCE_SUPERSEDED, EV_OPERATION_COMMITTED
from ..core.operations import Operation
from ..core.pages import build_page_text
from ..core.session import writer_session
from ..core.sources import parse_source
from ..errors import UsageError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("supersede", help="Mark a source as superseded by another.")
    p.add_argument("old_source_id")
    p.add_argument("new_source_id")
    p.add_argument("--wait", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    old_id, new_id = args.old_source_id, args.new_source_id
    old = repo.sources / f"{old_id}.md"
    new = repo.sources / f"{new_id}.md"
    if not old.exists():
        raise UsageError(f"source not found: {old_id}")
    if not new.exists():
        raise UsageError(f"replacement source not found: {new_id}")

    with writer_session(ctx, f"wiki supersede {old_id} {new_id}", wait_seconds=args.wait) as log:
        src = parse_source(old)
        fm = dict(src.frontmatter)
        fm["status"] = "superseded"
        fm["superseded_by"] = new_id
        new_text = build_page_text(fm, src.body)

        op = Operation.create(repo, "supersede", {"old": old_id, "new": new_id})
        op.stage_write(repo.rel(old), new_text)
        op.prepare()
        op.apply()
        log.append_many([
            {"operation_id": op.operation_id, "type": EV_SOURCE_SUPERSEDED,
             "source_id": old_id, "replacement_source_id": new_id},
            {"operation_id": op.operation_id, "type": EV_OPERATION_COMMITTED,
             "files_changed": op.changed_paths(), "source_id": old_id},
        ])
        op.mark_committed()

    if args.json:
        emit({"ok": True, "old": old_id, "new": new_id}, as_json=True)
    else:
        info(f"{old_id} superseded by {new_id}. Run `wiki rebuild` to refresh indexes.")
    return 0
