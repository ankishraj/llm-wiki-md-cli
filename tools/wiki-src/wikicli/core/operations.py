"""Operation journal + recovery state machine (plan section 2).

An operation is a staged, journalled, recoverable commit -- NOT a true
multi-file ACID transaction. Each operation lives under .wiki/ops/<id>/ with:

    request.json     what was asked
    plan.json        the file change set with before/after hashes
    status.json      durable phase
    analysis.json    (ingest) structured analysis
    backups/         copies of affected files (pre-change)
    staged/          new file contents (temp), applied via rename

Phases: created -> prepared -> applying -> applied -> committed
        with branches to: aborted | rolled_back | divergent

On the next mutating invocation, the CLI (holding the exclusive lock)
classifies any incomplete operation by comparing live file hashes against the
recorded before/after hashes, and acts mechanically. Only `divergent`
operations require explicit user choice.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .hashing import hash_file_text
from .ids import new_ulid, now_iso
from .paths import Repo

PHASE_CREATED = "created"
PHASE_PREPARED = "prepared"
PHASE_APPLYING = "applying"
PHASE_APPLIED = "applied"
PHASE_COMMITTED = "committed"
PHASE_ABORTED = "aborted"
PHASE_ROLLED_BACK = "rolled_back"
PHASE_DIVERGENT = "divergent"

INCOMPLETE_PHASES = {PHASE_CREATED, PHASE_PREPARED, PHASE_APPLYING, PHASE_APPLIED}
TERMINAL_PHASES = {PHASE_COMMITTED, PHASE_ABORTED, PHASE_ROLLED_BACK}


@dataclass
class FileChange:
    path: str                 # repo-relative POSIX path of the target file
    before_hash: str | None   # None => file did not exist before
    after_hash: str | None    # None => file is deleted by this change
    backup_path: str | None = None   # op-relative
    staged_path: str | None = None   # op-relative

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "backup_path": self.backup_path,
            "staged_path": self.staged_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileChange":
        return cls(
            path=d["path"],
            before_hash=d.get("before_hash"),
            after_hash=d.get("after_hash"),
            backup_path=d.get("backup_path"),
            staged_path=d.get("staged_path"),
        )


class Operation:
    def __init__(self, repo: Repo, operation_id: str, op_type: str):
        self.repo = repo
        self.operation_id = operation_id
        self.op_type = op_type
        self.changes: list[FileChange] = []
        self.phase = PHASE_CREATED
        self.request: dict = {}
        self.analysis: dict = {}
        self.meta: dict = {}

    # -- directory layout ---------------------------------------------------

    @property
    def dir(self) -> Path:
        return self.repo.op_dir(self.operation_id)

    @property
    def backups_dir(self) -> Path:
        return self.dir / "backups"

    @property
    def staged_dir(self) -> Path:
        return self.dir / "staged"

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def create(cls, repo: Repo, op_type: str, request: dict | None = None) -> "Operation":
        op = cls(repo, "op-" + new_ulid(), op_type)
        op.request = request or {}
        op.dir.mkdir(parents=True, exist_ok=True)
        op.backups_dir.mkdir(exist_ok=True)
        op.staged_dir.mkdir(exist_ok=True)
        op._write_request()
        op._set_phase(PHASE_CREATED)
        return op

    @classmethod
    def load(cls, repo: Repo, operation_id: str) -> "Operation":
        op = cls(repo, operation_id, op_type="unknown")
        status = json.loads((op.dir / "status.json").read_text(encoding="utf-8"))
        op.phase = status["phase"]
        op.op_type = status.get("op_type", "unknown")
        op.meta = status.get("meta", {})
        plan_path = op.dir / "plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            op.changes = [FileChange.from_dict(c) for c in plan.get("changes", [])]
        req_path = op.dir / "request.json"
        if req_path.exists():
            op.request = json.loads(req_path.read_text(encoding="utf-8"))
        an_path = op.dir / "analysis.json"
        if an_path.exists():
            op.analysis = json.loads(an_path.read_text(encoding="utf-8"))
        return op

    # -- staging ------------------------------------------------------------

    def stage_write(self, rel_path: str, new_content: str):
        """Stage a create-or-update of a canonical file."""
        target = self.repo.root / rel_path
        before = hash_file_text(target) if target.exists() else None
        safe = rel_path.replace("/", "__")
        staged_rel = f"staged/{safe}"
        (self.dir / staged_rel).write_text(new_content, encoding="utf-8")
        from .hashing import hash_text
        after = hash_text(new_content)
        backup_rel = None
        if before is not None:
            backup_rel = f"backups/{safe}"
            shutil.copy2(target, self.dir / backup_rel)
        self.changes.append(FileChange(rel_path, before, after, backup_rel, staged_rel))

    def stage_delete(self, rel_path: str):
        target = self.repo.root / rel_path
        if not target.exists():
            return
        before = hash_file_text(target)
        safe = rel_path.replace("/", "__")
        backup_rel = f"backups/{safe}"
        shutil.copy2(target, self.dir / backup_rel)
        self.changes.append(FileChange(rel_path, before, None, backup_rel, None))

    def prepare(self):
        self._write_plan()
        self._set_phase(PHASE_PREPARED)

    # -- apply (temp-file-plus-rename) -------------------------------------

    def apply(self):
        self._set_phase(PHASE_APPLYING)
        for change in self.changes:
            target = self.repo.root / change.path
            target.parent.mkdir(parents=True, exist_ok=True)
            if change.after_hash is None:
                # deletion
                if target.exists():
                    target.unlink()
            else:
                staged = self.dir / change.staged_path
                tmp = target.with_suffix(target.suffix + ".wikitmp")
                shutil.copy2(staged, tmp)
                os.replace(tmp, target)  # atomic rename on same filesystem
        self._set_phase(PHASE_APPLIED)

    def mark_committed(self):
        self._set_phase(PHASE_COMMITTED)

    # -- recovery classification -------------------------------------------

    def classify(self) -> str:
        """Compare live file hashes to recorded before/after hashes."""
        matches_before = True
        matches_after = True
        any_neither = False
        for change in self.changes:
            target = self.repo.root / change.path
            live = hash_file_text(target) if target.exists() else None
            if live != change.before_hash:
                matches_before = False
            if live != change.after_hash:
                matches_after = False
            if live != change.before_hash and live != change.after_hash:
                any_neither = True
        if any_neither:
            return PHASE_DIVERGENT
        if matches_after:
            return PHASE_APPLIED  # ready to finalise
        if matches_before:
            return PHASE_ABORTED  # nothing applied; safe to discard
        return PHASE_ROLLED_BACK  # partial: roll back to before

    def rollback(self):
        """Restore all affected files to their before-state."""
        for change in self.changes:
            target = self.repo.root / change.path
            if change.before_hash is None:
                # file did not exist before -> remove it
                if target.exists():
                    target.unlink()
            else:
                backup = self.dir / change.backup_path
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(target.suffix + ".wikitmp")
                shutil.copy2(backup, tmp)
                os.replace(tmp, target)
        self._set_phase(PHASE_ROLLED_BACK)

    def restore_before(self):
        self.rollback()

    def apply_after(self):
        """Force the after-state (used to resolve a divergent op deliberately)."""
        for change in self.changes:
            target = self.repo.root / change.path
            if change.after_hash is None:
                if target.exists():
                    target.unlink()
            else:
                staged = self.dir / change.staged_path
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(target.suffix + ".wikitmp")
                shutil.copy2(staged, tmp)
                os.replace(tmp, target)
        self._set_phase(PHASE_COMMITTED)

    def mark_divergent(self):
        self._set_phase(PHASE_DIVERGENT)

    def abort(self):
        self._set_phase(PHASE_ABORTED)

    # -- persistence helpers ------------------------------------------------

    def changed_paths(self) -> list[str]:
        return [c.path for c in self.changes]

    def _write_request(self):
        (self.dir / "request.json").write_text(json.dumps(self.request, indent=2), encoding="utf-8")

    def write_analysis(self, analysis: dict):
        self.analysis = analysis
        (self.dir / "analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")

    def _write_plan(self):
        plan = {
            "operation_id": self.operation_id,
            "op_type": self.op_type,
            "created_at": now_iso(),
            "changes": [c.as_dict() for c in self.changes],
        }
        (self.dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    def _set_phase(self, phase: str):
        self.phase = phase
        status = {
            "operation_id": self.operation_id,
            "op_type": self.op_type,
            "phase": phase,
            "updated_at": now_iso(),
            "meta": self.meta,
        }
        (self.dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")


def find_incomplete_operations(repo: Repo) -> list[str]:
    """Return ids of operations whose phase is not terminal."""
    if not repo.ops.is_dir():
        return []
    incomplete = []
    for d in sorted(repo.ops.iterdir()):
        status_file = d / "status.json"
        if not status_file.exists():
            continue
        try:
            status = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            incomplete.append(d.name)
            continue
        if status.get("phase") in INCOMPLETE_PHASES or status.get("phase") == PHASE_DIVERGENT:
            incomplete.append(d.name)
    return incomplete
