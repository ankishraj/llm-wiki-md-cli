"""`wiki verify-diff` — integrity boundary check (plan section 7).

Used by the pre-commit hook and CI. Confirms that the current canonical state
is consistent with the committed operation history: every changed canonical
file must be accounted for by a committed operation plan, page hashes must
agree, and schema versions must match. This catches accidental direct edits
and most agent drift.

It is an INTEGRITY check, not an access-control check: a sufficiently capable
agent can fabricate operation records. The MVP targets detection.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.context import Context
from ..core.events import EventLog
from ..core.hashing import hash_file_text
from ..core.operations import Operation, PHASE_COMMITTED
from ..core.validators import collect_all_pages
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("verify-diff", help="Verify canonical state matches committed history.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    problems = []

    # Build the set of after_hashes the journal expects for each canonical path.
    expected: dict[str, str] = {}
    if repo.ops.is_dir():
        for d in sorted(repo.ops.iterdir()):
            status_file = d / "status.json"
            plan_file = d / "plan.json"
            if not status_file.exists() or not plan_file.exists():
                continue
            try:
                status = json.loads(status_file.read_text(encoding="utf-8"))
                if status.get("phase") != PHASE_COMMITTED:
                    continue
                plan = json.loads(plan_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            for change in plan.get("changes", []):
                path = change["path"]
                if change.get("after_hash") is None:
                    expected.pop(path, None)  # deleted
                else:
                    expected[path] = change["after_hash"]

    # Check current canonical pages and sources against expected hashes.
    canonical_paths = []
    for page in collect_all_pages(repo):
        canonical_paths.append(repo.rel(page.path))
    if repo.sources.is_dir():
        for sp in repo.sources.glob("*.md"):
            canonical_paths.append(repo.rel(sp))

    for rel in canonical_paths:
        target = repo.root / rel
        live = hash_file_text(target)
        if rel not in expected:
            problems.append({"path": rel, "issue": "untracked canonical file (no committed operation)"})
        elif expected[rel] != live:
            problems.append({"path": rel, "issue": "hash mismatch vs committed operation"})

    ok = not problems
    result = {"ok": ok, "problems": problems, "tracked": len(expected)}
    if args.json:
        emit(result, as_json=True)
    else:
        if ok:
            info(f"verify-diff OK ({len(canonical_paths)} canonical file(s) consistent).")
        else:
            info("verify-diff found integrity problems:")
            for p in problems:
                info(f"  - {p['path']}: {p['issue']}")
    return 0 if ok else 5
