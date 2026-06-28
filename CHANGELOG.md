# Changelog

All notable changes to `llm-wiki-md-cli` are documented here. This project
adheres to [Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-06-28

Initial public release.

### Added
- `wiki` CLI shipped as a self-contained, reproducible `wiki.pyz` zipapp with a
  pinned SHA-256 checksum (no required external runtime dependencies).
- Commands: `init`, `doctor`, `ingest`, `promote`, `query`, `search`, `read`,
  `sources-for`, `retract`, `supersede`, `purge`, `rebuild`, `lint`, `audit`,
  `reviews`, `schema`, `recover`, `verify-diff`, `metrics`.
- Markdown- and directory-based canonical store with content-addressed sources,
  fenced claim blocks, a versioned/immutable page schema, and a scoped review
  queue.
- Staged, journalled mutations with crash recovery (`wiki recover`) and an
  integrity check (`wiki verify-diff`).
- Cross-platform OS-level locking using the Python standard library
  (`fcntl` / `msvcrt`), with an automatic atomic-directory fallback for
  filesystems where advisory locks are unsupported (e.g. WSL `/mnt/c`).
- Bundled, copy-pasteable agent skills (`wiki-master`, `wiki-query`,
  `wiki-maintain`, `wiki-docs`) and a one-page CLI cheatsheet.
- `bin/` launchers (`wiki`, `wiki.cmd`, `wiki.ps1`) and a PATH installer
  (`tools/install.py`).
- Pre-commit hook and GitHub Actions workflow running reproducibility/checksum
  checks, tests, lint, and verify-diff.

[0.1.2]: https://github.com/ankishraj/llm-wiki-md-cli/releases/tag/v0.1.2
