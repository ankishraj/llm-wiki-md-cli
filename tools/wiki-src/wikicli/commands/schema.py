"""`wiki schema ...` — schema lifecycle (plan sections 4, 5).

Subcommands:
  check               meta-validate the active schema
  list                list published schema versions
  restore --version   restore a published schema from embedded fallback (v1)
  propose <file>      stage a proposed new schema for review
  validate-proposal   meta-validate a proposed schema file
  migrate --to vN     run a deterministic migration to a new schema version

Ordinary ingest cannot modify the schema. Schemas are immutable once
published: a correction creates a new version; it never edits an existing one.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..core.context import Context
from ..core.events import EV_SCHEMA_MIGRATED, EventLog
from ..core.ids import new_ulid
from ..core.locking import EXCLUSIVE, repository_lock
from ..core.operations import Operation
from ..core.paths import Repo
from ..core.schema import (
    embedded_bootstrap_schema,
    load_active_schema,
    meta_validate,
    read_schema_lock,
    write_schema_lock,
)
from ..errors import UsageError, ValidationError, WikiError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("schema", help="Schema lifecycle commands.")
    ssub = p.add_subparsers(dest="schema_command", metavar="<subcommand>")
    ssub.required = True

    pc = ssub.add_parser("check", help="Meta-validate the active schema.")
    pc.add_argument("--json", action="store_true")
    pls = ssub.add_parser("list", help="List published schema versions.")
    pls.add_argument("--json", action="store_true")

    pr = ssub.add_parser("restore", help="Restore a published schema from embedded fallback.")
    pr.add_argument("--version", default="v1")
    pr.add_argument("--json", action="store_true")

    pp = ssub.add_parser("propose", help="Stage a proposed new schema.")
    pp.add_argument("file")
    pp.add_argument("--json", action="store_true")

    pv = ssub.add_parser("validate-proposal", help="Meta-validate a proposed schema file.")
    pv.add_argument("file")
    pv.add_argument("--json", action="store_true")

    pm = ssub.add_parser("migrate", help="Migrate to a new schema version.")
    pm.add_argument("--to", required=True, dest="to_version")
    pm.add_argument("--wait", type=float, default=0.0)
    pm.add_argument("--json", action="store_true")

    p.set_defaults(func=run)


def run(args) -> int:
    cmd = args.schema_command
    if cmd == "check":
        return _check(args)
    if cmd == "list":
        return _list(args)
    if cmd == "restore":
        return _restore(args)
    if cmd == "propose":
        return _propose(args)
    if cmd == "validate-proposal":
        return _validate_proposal(args)
    if cmd == "migrate":
        return _migrate(args)
    raise UsageError(f"unknown schema subcommand {cmd!r}")


def _check(args) -> int:
    repo = Repo.discover()
    try:
        version = read_schema_lock(repo)
        load_active_schema(repo)
        info(f"Active schema {version} is valid.") if not args.json else emit(
            {"ok": True, "version": version}, as_json=True)
        return 0
    except WikiError as exc:
        if args.json:
            emit({"ok": False, "error": exc.message}, as_json=True)
        else:
            info(f"Schema check failed: {exc.message}")
        return exc.exit_code


def _list(args) -> int:
    repo = Repo.discover()
    versions = []
    if repo.schemas.is_dir():
        versions = sorted(p.stem for p in repo.schemas.glob("v*.json"))
    active = None
    try:
        active = read_schema_lock(repo)
    except Exception:
        pass
    if args.json:
        emit({"active": active, "versions": versions}, as_json=True)
    else:
        for v in versions:
            info(f"{'* ' if v == active else '  '}{v}")
    return 0


def _restore(args) -> int:
    repo = Repo.discover()
    version = args.version
    if version != "v1":
        raise UsageError("Only v1 can be restored from the embedded fallback.")
    repo.schemas.mkdir(parents=True, exist_ok=True)
    target = repo.schema_version_path("v1")
    target.write_text(json.dumps(embedded_bootstrap_schema(), indent=2), encoding="utf-8")
    if not repo.schema_lock.exists():
        write_schema_lock(repo, "v1")
    info(f"Restored schema {version} from embedded fallback.")
    return 0


def _propose(args) -> int:
    repo = Repo.discover()
    src = Path(args.file)
    if not src.exists():
        raise UsageError(f"proposal file not found: {src}")
    schema = json.loads(src.read_text(encoding="utf-8"))
    meta_validate(schema)
    proposals = repo.schemas / "proposals"
    proposals.mkdir(exist_ok=True)
    dest = proposals / src.name
    shutil.copy2(src, dest)
    info(f"Proposal staged and meta-validated: {repo.rel(dest)}")
    return 0


def _validate_proposal(args) -> int:
    src = Path(args.file)
    if not src.exists():
        raise UsageError(f"proposal file not found: {src}")
    schema = json.loads(src.read_text(encoding="utf-8"))
    try:
        meta_validate(schema)
    except ValidationError as exc:
        if args.json:
            emit({"ok": False, "errors": exc.errors}, as_json=True)
        else:
            info("Proposal failed meta-validation:")
            for e in exc.errors:
                info(f"  - {e}")
        return exc.exit_code
    info("Proposal is valid.") if not args.json else emit({"ok": True}, as_json=True)
    return 0


def _migrate(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    to_version = args.to_version
    new_schema_path = repo.schema_version_path(to_version)
    if not new_schema_path.exists():
        # Look in proposals
        proposal = repo.schemas / "proposals" / f"{to_version}.json"
        if proposal.exists():
            new_schema = json.loads(proposal.read_text(encoding="utf-8"))
        else:
            raise UsageError(
                f"Schema {to_version} not found. Propose it first with "
                f"`wiki schema propose`."
            )
    else:
        new_schema = json.loads(new_schema_path.read_text(encoding="utf-8"))

    # Migration runs under the exclusive lock as an operation.
    op_id = "op-" + new_ulid()
    with repository_lock(repo.lock_file, repo.lock_meta_file, EXCLUSIVE,
                         wait_seconds=args.wait, operation_id=op_id,
                         command=f"wiki schema migrate --to {to_version}"):
        # 1-2: validate new schema against embedded meta-schema.
        meta_validate(new_schema)

        # Look for a migration script.
        migration_script = repo.migrations / f"{ctx.schema_version}-to-{to_version}.py"
        op = Operation.create(repo, "schema-migrate",
                              {"from": ctx.schema_version, "to": to_version})

        # 3-4: run deterministic migration over pages, validate each.
        migrated = _apply_migration(repo, migration_script, new_schema, op)

        # publish new schema (immutable)
        op.stage_write(repo.rel(new_schema_path), json.dumps(new_schema, indent=2) + "\n")
        # 5: update schema.lock
        op.stage_write(repo.rel(repo.schema_lock), to_version + "\n")
        op.prepare()
        op.apply()

        log = EventLog(repo.events)
        log.append(EV_SCHEMA_MIGRATED, operation_id=op.operation_id,
                   from_version=ctx.schema_version, to_version=to_version,
                   files_changed=op.changed_paths(), pages_migrated=migrated)
        op.mark_committed()

    info(f"Migrated schema {ctx.schema_version} -> {to_version} ({migrated} pages).")
    return 0


def _apply_migration(repo, migration_script: Path, new_schema: dict, op: Operation) -> int:
    """Run the migration. If a script exists it transforms each page's text;
    otherwise migration is a no-op transform that simply re-validates pages
    against the new schema (used for additive schema changes)."""
    from ..core import jsonschema_compat as jsonschema
    from ..core.validators import collect_all_pages
    from ..core.pages import build_page_text

    transform = None
    if migration_script.exists():
        ns: dict = {}
        exec(compile(migration_script.read_text(encoding="utf-8"),
                     str(migration_script), "exec"), ns)
        transform = ns.get("migrate_page")

    validator = jsonschema.Draft7Validator(new_schema)
    count = 0
    for page in collect_all_pages(repo):
        fm = dict(page.frontmatter)
        body = page.body
        if transform:
            fm, body = transform(fm, body)
        # validate against new schema
        errors = sorted(validator.iter_errors(fm), key=lambda e: list(e.path))
        if errors:
            msgs = [f"{repo.rel(page.path)}: {'/'.join(str(x) for x in e.path)}: {e.message}"
                    for e in errors]
            raise ValidationError("Migration produced invalid pages.", errors=msgs)
        new_text = build_page_text(fm, body)
        if new_text != page.raw_text:
            op.stage_write(repo.rel(page.path), new_text)
            count += 1
    return count
