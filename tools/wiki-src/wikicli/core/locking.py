"""Concrete OS-level readers-writer locking (plan section 1).

Query commands acquire a SHARED lock; mutating commands acquire an EXCLUSIVE
lock. The lock is held by an open file descriptor for the duration of the
command and released automatically when the process exits.

Backend selection is automatic and dependency-free:

  * POSIX   -> fcntl.flock (shared/exclusive, non-blocking probe + retry)
  * Windows -> msvcrt.locking (exclusive byte-range lock; shared approximated)
  * portalocker is used if importable, but is NOT required.

This module must never hard-depend on a third-party package: the zipapp ships
with no guaranteed site-packages, so the standard library is the floor. If no
OS locking primitive is available at all (extremely unusual), that is reported
as a distinct, accurate error -- never disguised as lock contention.

A neighbouring metadata file (repository.lock.meta.json) is DIAGNOSTIC ONLY.
The OS-level lock on repository.lock is authoritative.

For filesystems where advisory locking is unreliable (some network mounts),
config may declare locking unreliable; the session layer then refuses mutation
rather than pretending a lock provides guarantees it cannot.
"""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path

from ..errors import LockError

SHARED = "shared"
EXCLUSIVE = "exclusive"


# ---------------------------------------------------------------------------
# Backend detection. We prefer the stdlib primitives so the CLI works with a
# bare Python install and an empty site-packages (the zipapp case). portalocker
# is treated as an optional convenience, not a requirement.
# ---------------------------------------------------------------------------

_BACKEND = None  # "fcntl" | "msvcrt" | "portalocker" | None

try:  # POSIX
    import fcntl  # type: ignore
    _BACKEND = "fcntl"
except Exception:
    fcntl = None  # type: ignore

if _BACKEND is None:
    try:  # Windows
        import msvcrt  # type: ignore
        _BACKEND = "msvcrt"
    except Exception:
        msvcrt = None  # type: ignore

if _BACKEND is None:
    try:  # last-resort optional dependency
        import portalocker  # type: ignore
        _BACKEND = "portalocker"
    except Exception:
        portalocker = None  # type: ignore


class _Unavailable(Exception):
    """Raised when no OS locking primitive exists. Distinct from contention."""


class _Contended(Exception):
    """Raised when the lock is held by another process (a retryable state)."""


def locking_backend() -> "str | None":
    """Return the active backend name, or None if locking is unavailable."""
    return _BACKEND


def backend_available() -> bool:
    return _BACKEND is not None


# ---------------------------------------------------------------------------
# Low-level acquire/release per backend. Each _acquire raises _Contended on a
# would-block condition, _Unsupported when the filesystem cannot honour the
# primitive (e.g. flock on a WSL /mnt/c DrvFs mount), and returns on success.
# ---------------------------------------------------------------------------

import errno as _errno

# errnos that mean "another holder has it" -> retryable contention.
_CONTENDED_ERRNOS = {_errno.EACCES, _errno.EAGAIN, _errno.EWOULDBLOCK}
# errnos that mean "this filesystem does not support advisory locking" -> we
# must fall back rather than loop forever or cry contention. DrvFs (WSL on
# /mnt/c), some NFS/CIFS mounts, and a few others land here.
_UNSUPPORTED_ERRNOS = {
    _errno.ENOLCK, _errno.EINVAL, _errno.ENOSYS, _errno.ENOTSUP,
    getattr(_errno, "EOPNOTSUPP", _errno.ENOTSUP), getattr(_errno, "EPERM", _errno.EACCES),
}


class _Unsupported(Exception):
    """Raised when the active primitive can't operate on this filesystem."""


def _acquire(fd, mode: str) -> None:
    if _BACKEND == "fcntl":
        flag = fcntl.LOCK_SH if mode == SHARED else fcntl.LOCK_EX
        try:
            fcntl.flock(fd.fileno(), flag | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in _CONTENDED_ERRNOS:
                raise _Contended() from exc
            if exc.errno in _UNSUPPORTED_ERRNOS:
                raise _Unsupported() from exc
            # Unknown lock error: treat as unsupported so we fall back safely
            # rather than reporting phantom contention.
            raise _Unsupported() from exc
        return

    if _BACKEND == "msvcrt":
        # msvcrt has no shared mode; a shared request takes an exclusive lock,
        # which is conservative but correct (readers serialise on Windows).
        try:
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in _CONTENDED_ERRNOS or exc.errno == getattr(_errno, "EDEADLK", -1):
                raise _Contended() from exc
            raise _Unsupported() from exc
        return

    if _BACKEND == "portalocker":
        flag = portalocker.LOCK_SH if mode == SHARED else portalocker.LOCK_EX
        try:
            portalocker.lock(fd, flag | portalocker.LOCK_NB)
        except Exception as exc:
            raise _Contended() from exc
        return

    raise _Unavailable()


def _release(fd) -> None:
    try:
        if _BACKEND == "fcntl":
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        elif _BACKEND == "msvcrt":
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
        elif _BACKEND == "portalocker":
            portalocker.unlock(fd)
    except Exception:
        # Releasing is best-effort; the fd close below also drops the lock.
        pass


# ---------------------------------------------------------------------------
# Atomic-mkdir fallback lock. os.mkdir is atomic on every filesystem we care
# about (including DrvFs and NFS), so an exclusive lock-directory provides real
# mutual exclusion even where advisory byte-range locks do not work. It is
# coarser (exclusive-only; a SHARED request takes the exclusive dir, which is
# safe but serialises readers), and it cannot auto-release if the process is
# killed -9 -- so it records holder metadata and treats an entry whose PID is
# no longer alive on the same host as stale and reclaimable.
# ---------------------------------------------------------------------------

def _lockdir_for(lock_file: Path) -> Path:
    return lock_file.with_name(lock_file.name + ".d")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == _errno.EPERM  # exists but not ours
    except Exception:
        return False
    return True


def _acquire_lockdir(lock_file: Path, holder: dict) -> bool:
    d = _lockdir_for(lock_file)
    try:
        os.mkdir(d)
    except FileExistsError:
        # Possibly stale (holder died). Reclaim only if same host and dead PID.
        info = _read_meta(d / "owner.json")
        if info and info.get("hostname") == socket.gethostname():
            pid = info.get("pid")
            if isinstance(pid, int) and not _pid_alive(pid):
                try:
                    _rmdir_lockdir(d)
                    os.mkdir(d)
                except Exception:
                    return False
            else:
                return False
        else:
            return False
    try:
        (d / "owner.json").write_text(json.dumps(holder), encoding="utf-8")
    except Exception:
        pass
    return True


def _release_lockdir(lock_file: Path):
    _rmdir_lockdir(_lockdir_for(lock_file))


def _rmdir_lockdir(d: Path):
    try:
        owner = d / "owner.json"
        if owner.exists():
            owner.unlink()
        os.rmdir(d)
    except FileNotFoundError:
        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@contextmanager
def repository_lock(
    lock_file: Path,
    meta_file: Path,
    mode: str,
    *,
    wait_seconds: float = 0.0,
    operation_id: "str | None" = None,
    command: "str | None" = None,
):
    """Acquire the repository lock.

    Default is fail-fast (wait_seconds == 0). With wait_seconds > 0 we retry
    until the deadline before giving up. A missing locking backend is reported
    as its own error and never masquerades as contention.
    """
    if mode not in (SHARED, EXCLUSIVE):  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown lock mode {mode!r}")

    if not backend_available():
        raise LockError(
            "No OS file-locking primitive is available in this Python runtime.",
            detail=(
                "wiki could not find fcntl (POSIX), msvcrt (Windows), or "
                "portalocker. This is an environment problem, not lock "
                "contention. Run on a standard CPython build, or set a "
                "supported locking backend."
            ),
        )

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    # Keep the fd open for the whole critical section so the lock is held.
    fd = open(lock_file, "a+")
    deadline = time.monotonic() + max(0.0, wait_seconds)
    acquired = False
    use_lockdir = False  # set if the primitive turns out unsupported here
    holder_meta = {
        "operation_id": operation_id,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "command": command,
        "backend": _BACKEND,
        "started_at": _now(),
    }
    try:
        while True:
            try:
                if use_lockdir:
                    if _acquire_lockdir(lock_file, holder_meta):
                        acquired = True
                        break
                    raise _Contended()
                _acquire(fd, mode)
                acquired = True
                break
            except _Unsupported:
                # Advisory locking does not work on this filesystem (e.g. a WSL
                # /mnt/c DrvFs mount). Transparently switch to the atomic
                # lock-directory fallback, which provides real exclusion here.
                use_lockdir = True
                continue
            except _Contended:
                if time.monotonic() >= deadline:
                    src = _lockdir_for(lock_file) / "owner.json" if use_lockdir else meta_file
                    holder = _read_meta(src)
                    raise LockError(
                        _contention_message(holder),
                        detail="Another process holds the lock. Use --wait <seconds> to wait.",
                    )
                time.sleep(0.1)
            except _Unavailable as exc:  # pragma: no cover - guarded above
                raise LockError(
                    "OS file-locking primitive disappeared at runtime.",
                    detail=str(exc),
                )

        # Diagnostic metadata for exclusive (writer) holders only.
        if mode == EXCLUSIVE:
            _write_meta(meta_file, operation_id, command)
        try:
            yield
        finally:
            if mode == EXCLUSIVE:
                _clear_meta(meta_file)
    finally:
        if acquired:
            if use_lockdir:
                _release_lockdir(lock_file)
            else:
                _release(fd)
        fd.close()


def _write_meta(meta_file: Path, operation_id, command):
    data = {
        "operation_id": operation_id,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "command": command,
        "backend": _BACKEND,
        "started_at": _now(),
    }
    meta_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clear_meta(meta_file: Path):
    try:
        meta_file.unlink()
    except FileNotFoundError:
        pass


def _read_meta(meta_file: Path):
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def _contention_message(holder) -> str:
    if not holder:
        return "Wiki is locked by another process."
    op = holder.get("operation_id") or "?"
    host = holder.get("hostname") or "?"
    pid = holder.get("pid") or "?"
    return f"Wiki is locked by operation {op} on {host}, PID {pid}."


def _now() -> str:
    from .ids import now_iso
    return now_iso()
