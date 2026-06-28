"""Schema and embedded-asset loading (plan sections 4, 5, 6).

The CLI embeds a bootstrap schema and a meta-schema inside the package so that
diagnosis/restoration commands work even when the project schema is broken.

Startup validation order (enforced by callers):
  1. validate schema.lock
  2. validate the referenced schema against the embedded meta-schema
  3. validate configuration
  4. validate content

Schemas are immutable once published: a correction creates a new version, it
does not edit an existing one.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from ..errors import IntegrityError, ValidationError
from .paths import Repo

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


# -- embedded assets --------------------------------------------------------

def _embedded_text(name: str) -> str:
    return resources.files("wikicli.embedded").joinpath(name).read_text(encoding="utf-8")


def embedded_bootstrap_schema() -> dict:
    return json.loads(_embedded_text("bootstrap_schema_v1.json"))


def embedded_meta_schema() -> dict:
    return json.loads(_embedded_text("meta_schema.json"))


def embedded_default_config() -> str:
    return _embedded_text("default_config.toml")


# -- schema.lock ------------------------------------------------------------

def read_schema_lock(repo: Repo) -> str:
    """Return the active schema version, e.g. 'v1'. Validates the lock file."""
    if not repo.schema_lock.exists():
        raise IntegrityError(
            "schema.lock is missing.",
            detail="Run `wiki doctor` or `wiki schema restore`.",
        )
    text = repo.schema_lock.read_text(encoding="utf-8").strip()
    # schema.lock is a tiny file: a single version token, optionally JSON.
    if text.startswith("{"):
        try:
            data = json.loads(text)
            version = data.get("active") or data.get("version")
        except json.JSONDecodeError as exc:
            raise IntegrityError("schema.lock is malformed JSON.", detail=str(exc))
    else:
        version = text
    if not version or not _looks_like_version(version):
        raise IntegrityError(f"schema.lock contains an invalid version: {version!r}")
    return version


def write_schema_lock(repo: Repo, version: str):
    repo.schema_lock.write_text(version + "\n", encoding="utf-8")


def _looks_like_version(v: str) -> bool:
    return isinstance(v, str) and v.startswith("v") and v[1:].isdigit()


# -- schema loading + meta-validation --------------------------------------

def load_active_schema(repo: Repo) -> dict:
    """Load and meta-validate the active project schema (steps 1-2)."""
    version = read_schema_lock(repo)
    path = repo.schema_version_path(version)
    if not path.exists():
        raise IntegrityError(
            f"Active schema {version} not found at {path}.",
            detail="Run `wiki schema restore` to restore it.",
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"Schema {version} is malformed JSON.", detail=str(exc))
    meta_validate(schema)
    return schema


def meta_validate(schema: dict) -> None:
    """Validate a schema document against the embedded meta-schema."""
    from . import jsonschema_compat as jsonschema

    meta = embedded_meta_schema()
    validator = jsonschema.Draft7Validator(meta)
    errors = sorted(validator.iter_errors(schema), key=lambda e: e.path)
    if errors:
        msgs = [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise ValidationError("Schema failed meta-validation.", errors=msgs)
    # Also confirm jsonschema itself accepts it as a draft-07 schema.
    try:
        jsonschema.Draft7Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise ValidationError("Schema is not a valid JSON Schema.", errors=[str(exc)])


# -- config -----------------------------------------------------------------

def load_config(repo: Repo) -> dict:
    if tomllib is None:  # pragma: no cover
        raise IntegrityError("tomllib unavailable; Python 3.11+ required.")
    if not repo.config.exists():
        raise IntegrityError("config.toml is missing.", detail="Run `wiki doctor`.")
    try:
        return tomllib.loads(repo.config.read_text(encoding="utf-8"))
    except Exception as exc:
        raise IntegrityError("config.toml is malformed.", detail=str(exc))
