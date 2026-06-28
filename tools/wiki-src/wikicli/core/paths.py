"""Repository layout and path resolution.

Defines the canonical directory structure and provides a Repo object that
resolves all the important paths relative to a project root. Path discovery
walks upward from the current directory looking for a `.wiki` directory,
mirroring how git finds `.git`.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..errors import NotInitialised

# --- Top-level directories -------------------------------------------------

WIKI_DIR = "wiki"            # canonical knowledge
DOT_WIKI_DIR = ".wiki"       # canonical operational state + derived caches

# --- wiki/ subtree ---------------------------------------------------------

PAGES_DIR = "pages"
SOURCES_DIR = "sources"
RAW_DIR = "raw"
INDEX_FILE = "index.md"

PAGE_TYPES = ("topics", "entities", "decisions", "syntheses")

# --- .wiki/ subtree --------------------------------------------------------

CONFIG_FILE = "config.toml"
SCHEMA_LOCK_FILE = "schema.lock"
SCHEMAS_DIR = "schemas"
MIGRATIONS_DIR = "migrations"
EVENTS_FILE = "events.jsonl"
LOCKS_DIR = "locks"
LOCK_FILE = "repository.lock"
LOCK_META_FILE = "repository.lock.meta.json"
OPS_DIR = "ops"
REVIEWS_DIR = "reviews"
EVAL_DIR = "eval"
EVAL_RETRIEVAL_FILE = "retrieval.jsonl"
CACHE_DIR = "cache"

# Derived cache files
MANIFEST_FILE = "manifest.json"
BACKLINKS_FILE = "backlinks.json"
CLAIM_INDEX_FILE = "claim-index.json"
LINT_REPORT_FILE = "lint-report.json"
METRICS_FILE = "metrics.json"
QMD_CACHE_DIR = "qmd"


class Repo:
    """Resolves all paths for a wiki repository rooted at `root`."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # -- discovery ----------------------------------------------------------

    @classmethod
    def discover(cls, start: Path | None = None) -> "Repo":
        """Walk upward from `start` (or cwd) to find a .wiki directory."""
        cur = Path(start or os.getcwd()).resolve()
        for candidate in [cur, *cur.parents]:
            if (candidate / DOT_WIKI_DIR).is_dir():
                return cls(candidate)
        raise NotInitialised(
            "No wiki found in this directory or any parent.",
            detail="Run `wiki init` to create one.",
        )

    @classmethod
    def discover_or_none(cls, start: Path | None = None) -> "Repo | None":
        try:
            return cls.discover(start)
        except NotInitialised:
            return None

    @property
    def exists(self) -> bool:
        return self.dot_wiki.is_dir()

    # -- top level ----------------------------------------------------------

    @property
    def wiki(self) -> Path:
        return self.root / WIKI_DIR

    @property
    def dot_wiki(self) -> Path:
        return self.root / DOT_WIKI_DIR

    # -- wiki subtree -------------------------------------------------------

    @property
    def pages(self) -> Path:
        return self.wiki / PAGES_DIR

    def page_type_dir(self, page_type: str) -> Path:
        return self.pages / page_type

    @property
    def sources(self) -> Path:
        return self.wiki / SOURCES_DIR

    @property
    def raw(self) -> Path:
        return self.wiki / RAW_DIR

    @property
    def index_md(self) -> Path:
        return self.wiki / INDEX_FILE

    def raw_path_for_hash(self, sha256: str, ext: str) -> Path:
        prefix = sha256[:2]
        ext = ext.lstrip(".")
        name = f"{sha256}.{ext}" if ext else sha256
        return self.raw / "sha256" / prefix / name

    # -- .wiki subtree ------------------------------------------------------

    @property
    def config(self) -> Path:
        return self.dot_wiki / CONFIG_FILE

    @property
    def schema_lock(self) -> Path:
        return self.dot_wiki / SCHEMA_LOCK_FILE

    @property
    def schemas(self) -> Path:
        return self.dot_wiki / SCHEMAS_DIR

    def schema_version_path(self, version: str) -> Path:
        return self.schemas / f"{version}.json"

    @property
    def migrations(self) -> Path:
        return self.dot_wiki / MIGRATIONS_DIR

    @property
    def events(self) -> Path:
        return self.dot_wiki / EVENTS_FILE

    @property
    def locks(self) -> Path:
        return self.dot_wiki / LOCKS_DIR

    @property
    def lock_file(self) -> Path:
        return self.locks / LOCK_FILE

    @property
    def lock_meta_file(self) -> Path:
        return self.locks / LOCK_META_FILE

    @property
    def ops(self) -> Path:
        return self.dot_wiki / OPS_DIR

    def op_dir(self, operation_id: str) -> Path:
        return self.ops / operation_id

    @property
    def reviews(self) -> Path:
        return self.dot_wiki / REVIEWS_DIR

    def review_path(self, review_id: str) -> Path:
        return self.reviews / f"{review_id}.json"

    @property
    def eval(self) -> Path:
        return self.dot_wiki / EVAL_DIR

    @property
    def eval_retrieval(self) -> Path:
        return self.eval / EVAL_RETRIEVAL_FILE

    @property
    def cache(self) -> Path:
        return self.dot_wiki / CACHE_DIR

    @property
    def manifest(self) -> Path:
        return self.cache / MANIFEST_FILE

    @property
    def backlinks(self) -> Path:
        return self.cache / BACKLINKS_FILE

    @property
    def claim_index(self) -> Path:
        return self.cache / CLAIM_INDEX_FILE

    @property
    def lint_report(self) -> Path:
        return self.cache / LINT_REPORT_FILE

    @property
    def metrics_file(self) -> Path:
        return self.cache / METRICS_FILE

    @property
    def qmd_cache(self) -> Path:
        return self.cache / QMD_CACHE_DIR

    # -- helpers ------------------------------------------------------------

    def rel(self, path: Path) -> str:
        """Repository-relative POSIX path string for citations/logging."""
        return Path(path).resolve().relative_to(self.root).as_posix()

    def require_initialised(self) -> None:
        if not self.exists:
            raise NotInitialised(
                "This directory is not an initialised wiki.",
                detail="Run `wiki init`.",
            )
