"""Mutation/query session helpers.

A mutating command runs inside `writer_session`, which:
  * checks the locking backend is usable (refuses on unreliable filesystems
    unless configured otherwise),
  * acquires the EXCLUSIVE lock,
  * detects any incomplete operation and refuses until recovery establishes a
    consistent state (read-only queries also refuse if a partial state exists).

A query command runs inside `reader_session`, which acquires the SHARED lock
and likewise refuses if the repository is in a partial (recovery-required)
state.
"""

from __future__ import annotations

from contextlib import contextmanager

from ..errors import LockError, RecoveryRequired
from .context import Context
from .events import EventLog
from .locking import (
    EXCLUSIVE,
    SHARED,
    backend_available,
    locking_backend,
    repository_lock,
)
from .operations import find_incomplete_operations, PHASE_DIVERGENT, Operation


def _check_locking_usable(ctx: Context):
    # The locking backend must actually exist. With the stdlib backends this is
    # true on any normal CPython build; if it is somehow absent we say so
    # plainly rather than letting it surface later as misleading "contention".
    if not backend_available():
        raise LockError(
            "No OS file-locking primitive is available in this Python runtime.",
            detail=(
                "wiki needs fcntl (POSIX), msvcrt (Windows), or portalocker. "
                "This is an environment problem, not lock contention."
            ),
        )
    cfg = ctx.locking_cfg
    backend = cfg.get("backend", "os")
    reliable = cfg.get("reliable", True)
    if backend == "os" and not reliable:
        raise LockError(
            "Advisory locking is marked unreliable for this repository.",
            detail="Configure a supported locking backend before mutating.",
        )


def _guard_incomplete(ctx: Context, *, for_mutation: bool):
    incomplete = find_incomplete_operations(ctx.repo)
    if not incomplete:
        return
    # Distinguish divergent (needs explicit choice) from merely unfinished.
    op_id = incomplete[0]
    raise RecoveryRequired(
        f"An unfinished operation blocks this command: {op_id}.",
        operation_id=op_id,
        detail="Run `wiki recover --auto` (safe actions) or "
               f"`wiki recover {op_id} ...` for a divergent operation.",
    )


@contextmanager
def writer_session(ctx: Context, command: str, *, wait_seconds: float = 0.0, operation_id: str | None = None):
    _check_locking_usable(ctx)
    with repository_lock(
        ctx.repo.lock_file,
        ctx.repo.lock_meta_file,
        EXCLUSIVE,
        wait_seconds=wait_seconds,
        operation_id=operation_id,
        command=command,
    ):
        _guard_incomplete(ctx, for_mutation=True)
        yield EventLog(ctx.repo.events)


@contextmanager
def reader_session(ctx: Context, command: str, *, wait_seconds: float = 0.0):
    with repository_lock(
        ctx.repo.lock_file,
        ctx.repo.lock_meta_file,
        SHARED,
        wait_seconds=wait_seconds,
        command=command,
    ):
        # Queries refuse to run on a repository left partial by a crash.
        _guard_incomplete(ctx, for_mutation=False)
        yield EventLog(ctx.repo.events)
