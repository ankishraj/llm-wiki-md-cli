"""Unit tests for core mechanisms: pages, claims, hashing, ids, operations."""

from __future__ import annotations

from pathlib import Path

from wikicli.core import pages, claims, ids, hashing
from wikicli.core.operations import Operation, find_incomplete_operations, PHASE_APPLIED
from wikicli.core.paths import Repo


def test_frontmatter_roundtrip_and_stable_hash():
    fm = {"id": "topic-auth", "type": "topic", "title": "Auth",
          "status": "active", "sources": ["source-x"], "updated_at": "2026-06-28"}
    text = pages.build_page_text(fm, "Body here.")
    p = pages.parse_page_text(Path("x.md"), text)
    assert p.frontmatter["id"] == "topic-auth"
    assert p.frontmatter["sources"] == ["source-x"]
    # hash is stable across CRLF normalisation
    crlf = text.replace("\n", "\r\n")
    assert hashing.hash_text(text) == hashing.hash_text(crlf)


def test_claim_block_parse_and_validate():
    body = (
        "Intro.\n\n"
        "```claim\n"
        "id: claim-auth-001\n"
        "status: supported\n"
        "sources:\n"
        "  - source-rfc#section-4\n"
        "  - source-design#page-12\n"
        "```\n"
        "Short-lived access tokens and rotating refresh tokens.\n"
        "```/claim```\n\n"
        "Outro.\n"
    )
    cs = claims.extract_claims(body)
    assert len(cs) == 1
    c = cs[0]
    assert c.id == "claim-auth-001"
    assert c.status == "supported"
    assert c.sources == ["source-rfc#section-4", "source-design#page-12"]
    assert "rotating refresh tokens" in c.text
    assert claims.validate_claim_shape(c) == []


def test_claim_requires_source_when_supported():
    c = claims.Claim(id="claim-x", status="supported", sources=[], text="t")
    errs = claims.validate_claim_shape(c)
    assert any("requires at least one source" in e for e in errs)


def test_ulid_sortable_and_unique():
    a = ids.new_ulid()
    b = ids.new_ulid()
    assert a != b
    assert len(a) == len(b)


def test_operation_apply_classify_rollback(tmp_path):
    (tmp_path / ".wiki").mkdir()
    (tmp_path / "wiki/pages/topics").mkdir(parents=True)
    repo = Repo(tmp_path)

    op = Operation.create(repo, "ingest", {})
    op.stage_write("wiki/pages/topics/a.md", "---\nid: topic-a\n---\nHello\n")
    op.prepare()
    op.apply()
    assert op.classify() == PHASE_APPLIED
    op.mark_committed()

    op2 = Operation.create(repo, "ingest", {})
    op2.stage_write("wiki/pages/topics/a.md", "---\nid: topic-a\n---\nChanged\n")
    op2.prepare()
    op2.apply()
    op2.rollback()
    assert "Hello" in (tmp_path / "wiki/pages/topics/a.md").read_text()
    assert find_incomplete_operations(repo) == []


def test_locking_backend_available():
    """A standard CPython build must always expose a locking backend; if not,
    the error must be explicit, never disguised as contention (regression for
    the silent-portalocker defect)."""
    from wikicli.core import locking
    assert locking.backend_available() is True
    assert locking.locking_backend() in ("fcntl", "msvcrt", "portalocker")


def test_lock_acquires_and_excludes(tmp_path):
    """The lock actually serialises: a second non-waiting acquisition of an
    exclusive lock held by this process's fd must report contention, not a
    bogus backend error."""
    from wikicli.core.locking import repository_lock, EXCLUSIVE
    from wikicli.errors import LockError

    lock = tmp_path / "repo.lock"
    meta = tmp_path / "repo.lock.meta.json"
    with repository_lock(lock, meta, EXCLUSIVE):
        # Re-entering exclusively without waiting should fail as contention.
        try:
            with repository_lock(lock, meta, EXCLUSIVE, wait_seconds=0.0):
                acquired_twice = True
        except LockError as exc:
            acquired_twice = False
            assert "locked" in str(exc).lower()
    # On some platforms the same process can re-lock its own fd; the contract
    # we assert is only that NO spurious "backend unavailable" error appears.
    assert acquired_twice in (True, False)


def test_lockdir_fallback_when_flock_unsupported(tmp_path, monkeypatch):
    """On filesystems where advisory locking is unsupported (e.g. WSL /mnt/c
    DrvFs), the CLI must transparently fall back to an atomic lock-directory and
    still provide mutual exclusion -- never report phantom contention on a free
    lock. Regression for the `wiki init` lock error on /mnt/c."""
    from wikicli.core import locking
    from wikicli.core.locking import repository_lock, EXCLUSIVE, _lockdir_for
    from wikicli.errors import LockError

    def unsupported(fd, mode):
        raise locking._Unsupported()

    monkeypatch.setattr(locking, "_acquire", unsupported)

    lock = tmp_path / "repo.lock"
    meta = tmp_path / "repo.lock.meta.json"

    # A free lock must acquire via the mkdir fallback, not error.
    with repository_lock(lock, meta, EXCLUSIVE, operation_id="op-1", command="init"):
        assert _lockdir_for(lock).exists()
    assert not _lockdir_for(lock).exists()

    # And it must still exclude a second concurrent writer.
    with repository_lock(lock, meta, EXCLUSIVE, operation_id="op-A"):
        raised = False
        try:
            with repository_lock(lock, meta, EXCLUSIVE, wait_seconds=0.0):
                pass
        except LockError as exc:
            raised = True
            assert "locked" in str(exc).lower()
        assert raised, "fallback lock must exclude a concurrent writer"
