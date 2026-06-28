"""`wiki ingest <source>` — staged, journalled ingest (plan section 2).

Flow:
  1. Acquire the exclusive lock (writer_session).
  2. Fingerprint the source; decide embedded vs external storage by size.
  3. Register the source: copy raw blob (if embedded) and write a descriptor.
  4. Validate the proposed descriptor against schema rules.
  5. Back up affected files; apply via temp-file-plus-rename.
  6. Append source_ingested + operation_committed events.
  7. Rebuild affected derived indexes.

The model (the agent) is responsible for synthesis and contradiction analysis;
this command handles the deterministic mechanics: hashing, storage policy,
descriptor creation, staging, validation, journalling. Synthesis edits are
made by the agent through subsequent staged operations / page writes.

This command does NOT auto-synthesise prose. It registers provenance so that
the agent can then write/append claim-backed pages safely.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..core.context import Context
from ..core.events import EV_SOURCE_INGESTED, EV_OPERATION_COMMITTED
from ..core.hashing import hash_file
from ..core.operations import Operation
from ..core.session import writer_session
from ..core.sources import (
    EVIDENCE_CLASSES,
    SOURCE_ID_RE,
    build_source_descriptor,
    parse_source,
)
from ..errors import UsageError, ValidationError
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("ingest", help="Register a source into the wiki.")
    p.add_argument("source", help="Path to a local source file.")
    p.add_argument("--id", dest="source_id", help="Explicit source id (source-<slug>).")
    p.add_argument("--title", help="Human title for the source.")
    p.add_argument("--evidence-class", default="unknown", choices=EVIDENCE_CLASSES)
    p.add_argument("--summary", help="Short descriptor body text.")
    p.add_argument("--wait", type=float, default=0.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "source"


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    src_path = Path(args.source)
    if not src_path.exists():
        raise UsageError(f"source file not found: {src_path}")

    # Determine source id.
    if args.source_id:
        source_id = args.source_id
    else:
        source_id = "source-" + _slugify(src_path.stem)
    if not SOURCE_ID_RE.match(source_id):
        raise UsageError(f"invalid source id {source_id!r} (must match source-<slug>)")

    sha = hash_file(src_path)
    size = src_path.stat().st_size
    ext = src_path.suffix.lstrip(".")

    limits = ctx.storage_limits
    max_embedded = limits.get("max_embedded_source_bytes", 100 * 1024 * 1024)
    storage = "embedded" if size <= max_embedded else "external"

    descriptor_rel = repo.rel(repo.sources / f"{source_id}.md")

    with writer_session(ctx, f"wiki ingest {src_path}", wait_seconds=args.wait) as log:
        # Idempotency / duplicate detection.
        existing = repo.sources / f"{source_id}.md"
        if existing.exists():
            prev = parse_source(existing)
            if prev.sha256 == sha:
                if args.json:
                    emit({"ok": True, "source_id": source_id, "duplicate": True}, as_json=True)
                else:
                    info(f"Source {source_id} already ingested with identical content.")
                return 0
            raise UsageError(
                f"source id {source_id} exists with different content; "
                f"use --id to choose a new id or `wiki supersede`."
            )

        op = Operation.create(repo, "ingest", {
            "source": str(src_path), "source_id": source_id,
            "sha256": sha, "size": size, "storage": storage,
        })

        raw_rel = None
        if storage == "embedded":
            raw_target = repo.raw_path_for_hash(sha, ext)
            raw_rel = repo.rel(raw_target)
            # Copy raw blob into the operation's staged area first, then the
            # apply step renames into place. For raw blobs we copy directly
            # since they are content-addressed and immutable once present.
            raw_target.parent.mkdir(parents=True, exist_ok=True)
            if not raw_target.exists():
                tmp = raw_target.with_suffix(raw_target.suffix + ".wikitmp")
                shutil.copy2(src_path, tmp)
                import os
                os.replace(tmp, raw_target)
            # make read-only (best effort tamper-resistance)
            try:
                raw_target.chmod(0o444)
            except Exception:
                pass

        descriptor_text = build_source_descriptor(
            source_id=source_id,
            sha256=sha,
            size_bytes=size,
            storage=storage,
            raw_path=raw_rel,
            uri=(f"file://{src_path.resolve()}" if storage == "external" else None),
            evidence_class=args.evidence_class,
            classification_status="proposed",
            status="active",
            title=args.title,
            summary=args.summary,
            ext=ext,
            retrieval_hint=("mounted-local" if storage == "external" else None),
        )

        op.write_analysis({
            "source_id": source_id, "sha256": sha, "size_bytes": size,
            "storage": storage, "evidence_class": args.evidence_class,
        })

        op.stage_write(descriptor_rel, descriptor_text)

        # Validate the staged descriptor parses and has required fields.
        _validate_descriptor(descriptor_text, descriptor_rel)

        op.prepare()
        op.apply()

        log.append_many([
            {"operation_id": op.operation_id, "type": EV_SOURCE_INGESTED,
             "source_id": source_id, "sha256": sha, "storage": storage,
             "evidence_class": args.evidence_class},
            {"operation_id": op.operation_id, "type": EV_OPERATION_COMMITTED,
             "files_changed": op.changed_paths(), "source_id": source_id},
        ])
        op.mark_committed()

    # Rebuild derived state after the lock is released would race; instead we
    # mark that a rebuild is advisable. Caller can run `wiki rebuild`.
    if args.json:
        emit({"ok": True, "source_id": source_id, "sha256": sha,
              "storage": storage, "descriptor": descriptor_rel,
              "operation_id": op.operation_id}, as_json=True)
    else:
        info(f"Ingested {source_id} ({storage}, {size} bytes).")
        info(f"  descriptor: {descriptor_rel}")
        if raw_rel:
            info(f"  raw: {raw_rel}")
        info("  run `wiki rebuild` to refresh indexes.")
    return 0


def _validate_descriptor(text: str, rel: str):
    from ..core.pages import parse_page_text
    page = parse_page_text(Path(rel), text)
    fm = page.frontmatter
    required = ["source_id", "status", "sha256", "size_bytes", "storage", "evidence_class"]
    missing = [k for k in required if k not in fm]
    if missing:
        raise ValidationError(
            f"source descriptor missing required fields: {', '.join(missing)}",
            errors=missing,
        )
