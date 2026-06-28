"""`wiki purge <source-id> --confirm` — exceptional purge (plan section 13).

Removes the raw blob but retains a tombstone descriptor containing the former
identity and hash, so the source id remains resolvable. A purged source does
not create a broken reference; it creates an inactive but resolvable reference.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..core.context import Context
from ..core.events import EV_SOURCE_PURGED, EV_OPERATION_COMMITTED
from ..core.ids import now_iso
from ..core.operations import Operation
from ..core.session import writer_session
from ..core.sources import build_tombstone, parse_source
from ..errors import UsageError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("purge", help="Remove a source's raw blob, leaving a tombstone.")
    p.add_argument("source_id")
    p.add_argument("--confirm", action="store_true", required=False)
    p.add_argument("--reason", default="purged")
    p.add_argument("--wait", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    if not args.confirm:
        raise UsageError("purge is exceptional; pass --confirm to proceed.")
    ctx = Context.load()
    repo = ctx.repo
    sid = args.source_id
    descriptor = repo.sources / f"{sid}.md"
    if not descriptor.exists():
        raise UsageError(f"source not found: {sid}")

    with writer_session(ctx, f"wiki purge {sid}", wait_seconds=args.wait) as log:
        src = parse_source(descriptor)
        former_hash = src.sha256 or ""
        former_size = int(src.frontmatter.get("size_bytes", 0) or 0)
        raw_rel = src.raw_path

        tombstone = build_tombstone(
            source_id=sid,
            former_sha256=former_hash,
            former_size_bytes=former_size,
            purged_at=now_iso(),
            reason=args.reason,
            replacement_source_id=src.frontmatter.get("superseded_by"),
        )

        op = Operation.create(repo, "purge", {"source_id": sid, "reason": args.reason})
        op.stage_write(repo.rel(descriptor), tombstone)
        if raw_rel:
            op.stage_delete(raw_rel)
        op.prepare()
        # Raw files may be read-only; make writable so apply's delete works.
        if raw_rel:
            raw_target = repo.root / raw_rel
            if raw_target.exists():
                try:
                    raw_target.chmod(0o644)
                except Exception:
                    pass
        op.apply()
        log.append_many([
            {"operation_id": op.operation_id, "type": EV_SOURCE_PURGED,
             "source_id": sid, "former_sha256": former_hash, "reason": args.reason},
            {"operation_id": op.operation_id, "type": EV_OPERATION_COMMITTED,
             "files_changed": op.changed_paths(), "source_id": sid},
        ])
        op.mark_committed()

    if args.json:
        emit({"ok": True, "source_id": sid, "tombstone": True}, as_json=True)
    else:
        info(f"Purged {sid}. Tombstone retained; raw blob removed.")
    return 0
