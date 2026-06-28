"""`wiki doctor` — environment diagnostics (plan section 5).

Works even when the project schema is broken. Validates, in order:
  schema.lock -> active schema (meta) -> config -> events -> incomplete ops.
Reports problems and suggests remedies. Never mutates.
"""

from __future__ import annotations

from pathlib import Path

from ..core.context import Context
from ..core.events import EventLog
from ..core.operations import find_incomplete_operations
from ..core.paths import Repo
from ..core.schema import load_active_schema, load_config, read_schema_lock
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("doctor", help="Diagnose the wiki environment.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    repo = Repo.discover()
    checks = []

    def check(name, ok, message="", remedy=""):
        checks.append({"name": name, "ok": bool(ok), "message": message, "remedy": remedy})

    # initialised?
    check("initialised", repo.exists, "" if repo.exists else "no .wiki directory",
          "" if repo.exists else "run `wiki init`")

    # schema.lock
    version = None
    try:
        version = read_schema_lock(repo)
        check("schema.lock", True, f"active schema {version}")
    except Exception as exc:
        check("schema.lock", False, str(exc), "wiki schema restore")

    # active schema meta-validation
    if version:
        try:
            load_active_schema(repo)
            check("schema", True, f"{version} valid")
        except Exception as exc:
            check("schema", False, str(exc), f"wiki schema restore --version {version}")

    # config
    try:
        cfg = load_config(repo)
        check("config", True, f"contract {cfg.get('contract', {}).get('version', '?')}")
    except Exception as exc:
        check("config", False, str(exc), "restore config.toml from embedded default")

    # events
    try:
        log = EventLog(repo.events)
        malformed = log.malformed()
        if malformed:
            check("events", False, f"{len(malformed)} malformed event record(s)",
                  "inspect .wiki/events.jsonl")
        else:
            check("events", True, f"max seq {log.max_seq()}")
    except Exception as exc:
        check("events", False, str(exc))

    # incomplete operations
    incomplete = find_incomplete_operations(repo)
    if incomplete:
        check("operations", False, f"{len(incomplete)} incomplete operation(s): {', '.join(incomplete)}",
              "wiki recover --auto")
    else:
        check("operations", True, "no incomplete operations")

    # locking backend availability
    try:
        from ..core.locking import backend_available, locking_backend
        if backend_available():
            check("locking", True, f"backend: {locking_backend()}")
        else:
            check("locking", False, "no OS file-locking primitive available",
                  "run on a standard CPython build")
    except Exception as exc:
        check("locking", False, str(exc))

    ok = all(c["ok"] for c in checks)
    result = {"ok": ok, "checks": checks}

    if args.json:
        emit(result, as_json=True)
    else:
        info("wiki doctor")
        for c in checks:
            mark = "OK " if c["ok"] else "FAIL"
            line = f"  [{mark}] {c['name']}"
            if c["message"]:
                line += f": {c['message']}"
            info(line)
            if not c["ok"] and c["remedy"]:
                info(f"         -> {c['remedy']}")
        info("")
        info("All checks passed." if ok else "Some checks failed.")
    return 0 if ok else 4
