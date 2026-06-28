"""Runtime context: load + validate the environment for a command.

Enforces the startup validation order from plan section 5:
  1. validate schema.lock
  2. validate the referenced schema against the embedded meta-schema
  3. validate configuration
  4. (content validation happens in lint/verify, not here)

Diagnostic commands (doctor, schema *, recover) deliberately tolerate a broken
project schema and operate from embedded fallbacks; they construct the context
with require_schema=False.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import Repo
from .schema import (
    embedded_bootstrap_schema,
    embedded_default_config,
    load_active_schema,
    load_config,
    read_schema_lock,
)


@dataclass
class Context:
    repo: Repo
    config: dict
    schema: dict
    schema_version: str
    schema_ok: bool
    schema_error: str | None = None

    @classmethod
    def load(cls, start: Path | None = None, *, require_schema: bool = True) -> "Context":
        repo = Repo.discover(start)
        repo.require_initialised()

        schema_ok = True
        schema_error = None
        schema = None
        version = None

        # Steps 1-2: schema.lock + meta-validate referenced schema.
        try:
            version = read_schema_lock(repo)
            schema = load_active_schema(repo)
        except Exception as exc:
            schema_ok = False
            schema_error = str(exc)
            if require_schema:
                raise
            schema = embedded_bootstrap_schema()
            version = schema.get("schemaVersion", "v1")

        # Step 3: config.
        try:
            config = load_config(repo)
        except Exception:
            if require_schema:
                raise
            import tomllib
            config = tomllib.loads(embedded_default_config())

        return cls(
            repo=repo,
            config=config,
            schema=schema,
            schema_version=version,
            schema_ok=schema_ok,
            schema_error=schema_error,
        )

    # Convenience accessors -------------------------------------------------

    @property
    def default_stale_after(self) -> int:
        return int(self.config.get("reviews", {}).get("default_stale_after_operations", 20))

    @property
    def storage_limits(self) -> dict:
        return self.config.get("storage", {})

    @property
    def retrieval_cfg(self) -> dict:
        return self.config.get("retrieval", {})

    @property
    def locking_cfg(self) -> dict:
        return self.config.get("locking", {})
