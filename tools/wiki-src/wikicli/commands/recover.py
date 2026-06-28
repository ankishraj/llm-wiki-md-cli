"""`wiki recover` — drive the recovery state machine (plan section 2).

`wiki recover --auto` performs only provably safe actions: it classifies each
incomplete operation by comparing live file hashes to recorded before/after
hashes and acts mechanically:

  all match before_hash         -> abort (discard)
  all match after_hash + valid  -> finalise commit
  mixed before/after            -> roll back automatically
  any file matches neither      -> mark divergent and refuse

For a divergent operation, explicit intent is required:
  wiki recover <id> --keep-live | --restore-before | --apply-after
"""

from __future__ import annotations

from ..core.context import Context
from ..core.events import (
    EV_OPERATION_ABORTED,
    EV_OPERATION_COMMITTED,
    EV_OPERATION_ROLLED_BACK,
    EventLog,
)
from ..core.locking import EXCLUSIVE, repository_lock
from ..core.operations import (
    Operation,
    PHASE_ABORTED,
    PHASE_APPLIED,
    PHASE_DIVERGENT,
    PHASE_ROLLED_BACK,
    find_incomplete_operations,
)
from ..errors import UsageError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("recover", help="Recover incomplete operations.")
    p.add_argument("operation_id", nargs="?", help="Specific operation to recover.")
    p.add_argument("--auto", action="store_true", help="Perform only provably safe recovery.")
    p.add_argument("--keep-live", action="store_true")
    p.add_argument("--restore-before", action="store_true")
    p.add_argument("--apply-after", action="store_true")
    p.add_argument("--wait", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load(require_schema=False)
    repo = ctx.repo
    actions = []

    with repository_lock(repo.lock_file, repo.lock_meta_file, EXCLUSIVE,
                         wait_seconds=args.wait, command="wiki recover"):
        log = EventLog(repo.events)
        incomplete = find_incomplete_operations(repo)
        if not incomplete:
            if args.json:
                emit({"ok": True, "actions": []}, as_json=True)
            else:
                info("No incomplete operations.")
            return 0

        targets = [args.operation_id] if args.operation_id else incomplete

        for op_id in targets:
            if op_id not in incomplete:
                raise UsageError(f"{op_id} is not an incomplete operation.")
            op = Operation.load(repo, op_id)
            verdict = op.classify()

            if verdict == PHASE_DIVERGENT:
                actions.append(_handle_divergent(args, op, log))
                continue

            if args.auto or not args.operation_id:
                actions.append(_handle_safe(verdict, op, log))
            else:
                # explicit single-op without --auto and not divergent: still
                # apply the mechanical verdict.
                actions.append(_handle_safe(verdict, op, log))

    if args.json:
        emit({"ok": True, "actions": actions}, as_json=True)
    else:
        for a in actions:
            info(f"  {a['operation_id']}: {a['action']}")
    return 0


def _handle_safe(verdict, op: Operation, log: EventLog) -> dict:
    if verdict == PHASE_APPLIED:
        op.mark_committed()
        log.append(EV_OPERATION_COMMITTED, operation_id=op.operation_id,
                   files_changed=op.changed_paths(), recovered=True)
        return {"operation_id": op.operation_id, "action": "finalised commit"}
    if verdict == PHASE_ABORTED:
        op.abort()
        log.append(EV_OPERATION_ABORTED, operation_id=op.operation_id, recovered=True)
        return {"operation_id": op.operation_id, "action": "aborted (nothing applied)"}
    if verdict == PHASE_ROLLED_BACK:
        op.rollback()
        log.append(EV_OPERATION_ROLLED_BACK, operation_id=op.operation_id,
                   target_operation_id=op.operation_id, files_changed=op.changed_paths(),
                   recovered=True)
        return {"operation_id": op.operation_id, "action": "rolled back partial apply"}
    return {"operation_id": op.operation_id, "action": f"no action ({verdict})"}


def _handle_divergent(args, op: Operation, log: EventLog) -> dict:
    if args.keep_live:
        op.mark_committed()
        log.append(EV_OPERATION_COMMITTED, operation_id=op.operation_id,
                   files_changed=op.changed_paths(), divergent_resolution="keep-live")
        return {"operation_id": op.operation_id, "action": "kept live state"}
    if args.restore_before:
        op.restore_before()
        log.append(EV_OPERATION_ROLLED_BACK, operation_id=op.operation_id,
                   target_operation_id=op.operation_id, divergent_resolution="restore-before")
        return {"operation_id": op.operation_id, "action": "restored before-state"}
    if args.apply_after:
        op.apply_after()
        log.append(EV_OPERATION_COMMITTED, operation_id=op.operation_id,
                   files_changed=op.changed_paths(), divergent_resolution="apply-after")
        return {"operation_id": op.operation_id, "action": "forced after-state"}
    op.mark_divergent()
    return {
        "operation_id": op.operation_id,
        "action": "DIVERGENT - needs --keep-live | --restore-before | --apply-after",
    }
