"""`wiki init` — scaffold a wiki. Idempotent: safe to run repeatedly.

Inspects the project before creating anything, writes the directory
conventions, embedded schema v1, default config, schema.lock, an initial
empty index, and appends an `initialised` event.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import CONTRACT_VERSION
from ..core.events import EV_INITIALISED, EventLog
from ..core.ids import new_ulid
from ..core.locking import EXCLUSIVE, repository_lock
from ..core.paths import Repo, PAGE_TYPES
from ..core.schema import embedded_bootstrap_schema, embedded_default_config, write_schema_lock
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("init", help="Initialise a wiki in the current directory (idempotent).")
    p.add_argument("--root", default=".", help="Project root (default: current directory).")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    root = Path(args.root).resolve()
    repo = Repo(root)
    created = []

    def ensure_dir(path: Path):
        if not path.exists():
            path.mkdir(parents=True)
            created.append(repo.rel(path) if path != root else ".")

    # Directory conventions.
    ensure_dir(repo.wiki)
    ensure_dir(repo.pages)
    for t in PAGE_TYPES:
        ensure_dir(repo.pages / t)
    ensure_dir(repo.sources)
    ensure_dir(repo.raw / "sha256")
    ensure_dir(repo.dot_wiki)
    ensure_dir(repo.schemas)
    ensure_dir(repo.migrations)
    ensure_dir(repo.locks)
    ensure_dir(repo.ops)
    ensure_dir(repo.reviews)
    ensure_dir(repo.eval)
    ensure_dir(repo.cache)

    # Embedded schema v1 (immutable once published).
    schema_v1_path = repo.schema_version_path("v1")
    if not schema_v1_path.exists():
        schema_v1_path.write_text(
            json.dumps(embedded_bootstrap_schema(), indent=2), encoding="utf-8"
        )
        created.append(repo.rel(schema_v1_path))

    # schema.lock
    if not repo.schema_lock.exists():
        write_schema_lock(repo, "v1")
        created.append(repo.rel(repo.schema_lock))

    # config.toml
    if not repo.config.exists():
        repo.config.write_text(embedded_default_config(), encoding="utf-8")
        created.append(repo.rel(repo.config))

    # events.jsonl + initial event
    first_init = not repo.events.exists()
    if first_init:
        repo.events.touch()
        with repository_lock(repo.lock_file, repo.lock_meta_file, EXCLUSIVE,
                             operation_id="op-" + new_ulid(), command="wiki init"):
            EventLog(repo.events).append(
                EV_INITIALISED, operation_id="op-" + new_ulid(),
                contract_version=CONTRACT_VERSION,
            )
        created.append(repo.rel(repo.events))

    # initial empty index
    if not repo.index_md.exists():
        repo.index_md.write_text(
            "# Wiki Index\n\nGenerated routing index. Do not hand-edit.\n",
            encoding="utf-8",
        )
        created.append(repo.rel(repo.index_md))

    # eval placeholder
    if not repo.eval_retrieval.exists():
        repo.eval_retrieval.write_text("", encoding="utf-8")

    result = {
        "root": str(root),
        "created": created,
        "already_initialised": not first_init and not created,
        "contract_version": CONTRACT_VERSION,
    }
    if args.json:
        emit(result, as_json=True)
    else:
        if created:
            info(f"Initialised wiki at {root}")
            for c in created:
                info(f"  + {c}")
        else:
            info(f"Wiki already initialised at {root} (nothing to do).")
    return 0
