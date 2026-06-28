"""`wiki reviews ...` — review queue lifecycle (plan section 15).

Subcommands:
  list [--state S] [--severity X]   list review items
  show <review-id>                  show one review in detail
  resolve <review-id> --note ...    mark a review resolved
  defer <review-id> --note ...      defer a review
  stale                             evaluate staleness (scope-intersecting ops)

Blocking reviews are SCOPED: they prevent mutations to the affected page or
claim, not the whole wiki. Reviews are never silently deleted; they transition
between states.
"""

from __future__ import annotations

from ..core.context import Context
from ..core.events import EV_REVIEW_RESOLVED, EventLog
from ..core.locking import EXCLUSIVE, repository_lock
from ..core.reviews import (
    ReviewStore,
    STATE_DEFERRED,
    STATE_RESOLVED,
    evaluate_staleness,
)
from ..errors import UsageError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("reviews", help="Inspect and resolve the review queue.")
    sub = p.add_subparsers(dest="reviews_command", metavar="<subcommand>")
    sub.required = True

    pl = sub.add_parser("list", help="List review items.")
    pl.add_argument("--state")
    pl.add_argument("--severity")
    pl.add_argument("--json", action="store_true")

    ps = sub.add_parser("show", help="Show one review.")
    ps.add_argument("review_id")
    ps.add_argument("--json", action="store_true")

    pr = sub.add_parser("resolve", help="Resolve a review.")
    pr.add_argument("review_id")
    pr.add_argument("--note", default="")
    pr.add_argument("--wait", type=float, default=0.0)
    pr.add_argument("--json", action="store_true")

    pd = sub.add_parser("defer", help="Defer a review.")
    pd.add_argument("review_id")
    pd.add_argument("--note", default="")
    pd.add_argument("--wait", type=float, default=0.0)
    pd.add_argument("--json", action="store_true")

    pst = sub.add_parser("stale", help="Evaluate review staleness.")
    pst.add_argument("--wait", type=float, default=0.0)
    pst.add_argument("--json", action="store_true")

    p.set_defaults(func=run)


def run(args) -> int:
    cmd = args.reviews_command
    if cmd == "list":
        return _list(args)
    if cmd == "show":
        return _show(args)
    if cmd == "resolve":
        return _transition(args, STATE_RESOLVED)
    if cmd == "defer":
        return _transition(args, STATE_DEFERRED)
    if cmd == "stale":
        return _stale(args)
    raise UsageError(f"unknown reviews subcommand {cmd!r}")


def _list(args) -> int:
    ctx = Context.load(require_schema=False)
    store = ReviewStore(ctx.repo)
    reviews = store.all()
    if args.state:
        reviews = [r for r in reviews if r.state == args.state]
    if args.severity:
        reviews = [r for r in reviews if r.severity == args.severity]
    data = [r.as_dict() for r in reviews]
    if args.json:
        emit({"reviews": data}, as_json=True)
    else:
        if not reviews:
            info("No matching reviews.")
        for r in reviews:
            info(f"  [{r.state}/{r.severity}] {r.review_id}  {r.reason}")
            info(f"      scope={r.scope} created_seq={r.created_seq} stale_after={r.stale_after_operations}")
    return 0


def _show(args) -> int:
    ctx = Context.load(require_schema=False)
    store = ReviewStore(ctx.repo)
    review = store.get(args.review_id)
    if not review:
        raise UsageError(f"review not found: {args.review_id}")
    if args.json:
        emit(review.as_dict(), as_json=True)
    else:
        d = review.as_dict()
        for k, v in d.items():
            info(f"  {k}: {v}")
    return 0


def _transition(args, new_state) -> int:
    ctx = Context.load(require_schema=False)
    repo = ctx.repo
    store = ReviewStore(repo)
    review = store.get(args.review_id)
    if not review:
        raise UsageError(f"review not found: {args.review_id}")
    with repository_lock(repo.lock_file, repo.lock_meta_file, EXCLUSIVE,
                         wait_seconds=args.wait, command=f"wiki reviews {new_state}"):
        store.transition(review, new_state, resolution=args.note or new_state)
        if new_state == STATE_RESOLVED:
            EventLog(repo.events).append(
                EV_REVIEW_RESOLVED, operation_id="op-review",
                review_id=review.review_id, note=args.note)
    if args.json:
        emit({"ok": True, "review_id": review.review_id, "state": new_state}, as_json=True)
    else:
        info(f"Review {review.review_id} -> {new_state}.")
    return 0


def _stale(args) -> int:
    ctx = Context.load(require_schema=False)
    repo = ctx.repo
    with repository_lock(repo.lock_file, repo.lock_meta_file, EXCLUSIVE,
                         wait_seconds=args.wait, command="wiki reviews stale"):
        became = evaluate_staleness(repo)
    ids = [r.review_id for r in became]
    if args.json:
        emit({"ok": True, "newly_stale": ids}, as_json=True)
    else:
        if ids:
            info(f"{len(ids)} review(s) became stale:")
            for i in ids:
                info(f"  {i}")
        else:
            info("No reviews became stale.")
    return 0
