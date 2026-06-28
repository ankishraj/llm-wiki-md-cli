# LLM Wiki on Markdown with CLI & Skills 
**A project-local, Markdown-and-directory-based knowledge base that lives beside your code and is maintained by your AI coding agent through a single CLI.** No database, no Obsidian, no daemon — just plain files, cross-platform, with the CLI and agent skills bundled and ready to drop in.

[What & Why](#what--why) · [Features](#features) · [Installation](#installation) · [Getting Started](#getting-started) · [Skills & CLI](#skills--cli) · [Acknowledgements](#acknowledgements) · [Contributing](#contributing) · [License](#license)

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg) ![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg) ![Platforms](https://img.shields.io/badge/Platforms-Linux%20%7C%20macOS%20%7C%20Windows%20%7C%20WSL-lightgrey.svg)

## Author's Note

> **Full Disclosure:** This project was built for personal use and is entirely vibe coded. Please be aware of the associated risks.

I built this because it solves two big pain points I had with the existing LLM Wiki implementations.
- Personally - I am unfamiliar with Obsidian and building this seemed easier than learning it.
- Professionally - I work in a large corporation with strict IT policies and cannot install software (e.g. Obsidian) without IT approvals, but I already have Python.

Figured others might be in a similar boat. Enjoy, and feel free to build on it.

## What & Why

`llm-wiki-md-cli` is a knowledge base for a single project: topics, entities,
decisions and **syntheses** (written-up answers), each backed by cited sources.
It is **Markdown- and directory-based** — every page and source is a plain file
on disk, so it reads in any editor, diffs in git, and needs no database,
Obsidian, web app, or background process.

The point is that an AI coding agent maintains it for you. It is **designed to
run natively with GitHub Copilot, Claude Code, and Codex** with minimal setup:
the repository ships **a CLI and agent skills bundled together**, so an agent
can ingest sources, write claim-backed pages, and keep everything consistent
without you wiring anything up.

Why a CLI instead of letting the agent edit files freely? Because free-form
edits drift — links rot, claims lose their sources, two pages quietly
contradict. Here, **Markdown is canonical** and every change flows through the
`wiki` CLI, which validates, locks, journals, and records provenance. Indexes,
backlinks and caches are **disposable derived state**, always rebuildable from
the canonical files.

It is **cross-platform** (Linux, macOS, Windows, WSL) and **easy to set up** —
one build step produces a self-contained, dependency-free zipapp you reuse for
every project.

## Features

- **Markdown- and directory-based.** Pages and sources are plain `.md` files in
  a conventional folder layout. Human-readable, git-diffable, editor-agnostic.
- **No database, no Obsidian, no daemon.** Nothing to install or run in the
  background; the knowledge base *is* the files in your repo.
- **Cross-platform.** Works on Linux, macOS, Windows and WSL, using only the
  Python standard library for OS-level locking (`fcntl` / `msvcrt`), with an
  automatic atomic-directory fallback for filesystems where advisory locks
  aren't supported (e.g. WSL `/mnt/c` mounts).
- **CLI + agent skills bundled.** Ships a `wiki` CLI *and* ready-to-copy agent
  skills, so Copilot / Claude Code / Codex can operate it natively with minimal
  setup.
- **Self-contained, reproducible zipapp.** The CLI is a single `wiki.pyz` with a
  pinned SHA-256 checksum and a byte-reproducible build — no external runtime
  dependencies, verified in CI.
- **Source provenance with a lifecycle.** Every source is content-addressed by
  hash and tracked through `active → retracted → superseded → purged`, with a
  tombstone on purge so references never dangle.
- **Claim-backed pages.** Syntheses and decisions carry fenced, greppable claim
  blocks that cite specific sources; a "supported" claim must keep at least one
  active source behind it.
- **Deterministic linting + semantic audit.** `wiki lint` runs mechanical
  checks that can block a commit (broken links, unsupported claims, size
  budgets); `wiki audit` runs judgement-based checks that open *review items*
  instead of blocking.
- **Scoped review queue.** Issues (e.g. a claim that just lost its only source)
  become reviews that block mutations to the affected page/claim only — not the
  whole wiki — and age out as their area changes.
- **Crash-safe by design.** Mutations are staged and journalled; after an
  interruption the next command refuses until `wiki recover` safely finalises,
  aborts, or rolls back — and flags genuinely ambiguous cases for an explicit
  decision.
- **Versioned schema with migrations.** Page structure is governed by a
  versioned, immutable schema; `wiki schema migrate` validates every page
  against a new version atomically.
- **Integrity checks for CI.** `wiki verify-diff` confirms the files on disk
  match the recorded change history, catching accidental hand-edits; a
  pre-commit hook and GitHub Actions workflow are included.

---

## Installation

### Prerequisites

- **Python 3.11 or newer** (mandatory) — the only runtime requirement. Check
  with `python3 --version`. The CLI uses just the standard library at runtime.
- **`make`** (optional) — convenience targets (`make wiki`, `make install`). If
  you don't have it, run the equivalent `python3 tools/…` commands shown below.
- **`git`** (optional) — only needed for the included pre-commit hook and to
  clone the repo.
- **`jsonschema`, `portalocker`, `pytest`** (optional, dev only) — needed to run
  the test suite; never required to *use* the built CLI.

### Build the CLI (once)

The only build step is producing the `wiki.pyz` zipapp, and you do it
**once** — the resulting `tools/wiki.pyz` is a self-contained, dependency-free
artifact you reuse for every project.

```bash
# from this repo's root, once:
make wiki                 # builds tools/wiki.pyz + tools/wiki.pyz.sha256
```

No `make`? Call the builder directly (works on any platform):

```bash
python3 tools/build_pyz.py        # macOS / Linux
```
```powershell
python tools\build_pyz.py         # Windows (PowerShell or cmd)
```

You only rebuild when the CLI source under `tools/wiki-src/` changes.


At runtime a wiki creates `wiki/` (canonical knowledge) and `.wiki/`
(operational state + caches) in the project root. See `CONTRACT.md` for the
full canonical layout, page taxonomy, citation and claim syntax, and source
lifecycle.

### Put `wiki` on your PATH (once, optional)
So you (and any agent) can run `wiki` from any project without knowing where
this repo lives, add the repo's `bin/` directory to PATH. `bin/` contains only
the launchers (`wiki`, `wiki.cmd`, `wiki.ps1`); each resolves back to
`tools/wiki.pyz`. The installer is idempotent.

```bash
make install                      # or: python3 tools/install.py
source ~/.bashrc                  # or open a new terminal
wiki --version
```
```powershell
python tools\install.py           # writes your PowerShell profile
# open a new PowerShell/Bash window, then:
wiki --version
```
If no errors reported and you just see the version number printed, you are good to go.

Prefer to do it by hand, or just see what it would add? `python3
tools/install.py --print-only` prints the one line to drop in your shell rc /
profile (it's `export PATH="…/bin:$PATH"`). You can also symlink
`bin/wiki` into a directory already on PATH (e.g. `~/.local/bin`).

If you are unable to update the PATH due to administrator settings e.g. corporate environemnt, you can ask your Agent to set up an alias for it.

```bash
alias wiki="path/to/your/llm-wiki-md-cli/bin/wiki"        # on mac/linux
alias wiki="path\to\your\llm-wiki-md-cli\bin\wiki.cmd"    # on Windows (cmd)
alias wiki="path\to\your\llm-wiki-md-cli\bin\wiki.ps1"    # on Windows (PowerShell)
```

If using this method, note the following.
> - An alias is only active until you close your terminal. You can make it permanent by adding it to your shell's startup file (e.g. ~/.bashrc for bash, ~/.zshrc for zsh, or PowerShell profile for PowerShell).
> - Replace "path/to/your/llm-wiki-md-cli" with the actual path to your llm-wiki-md-cli directory.

Failing all the above, you may just provide your Agent with the exact path to your `llm-wiki-md-cli/bin`` directory.

## Getting Started

`make wiki` and `make install` are **not** run per project — they're one-time
setup. To create a wiki, `cd` into any project and run `wiki init`. It creates
`wiki/` and `.wiki/` in the current directory and is idempotent.

```bash
cd /path/to/your/project
wiki init
wiki ingest path/to/source.txt --id source-rfc --evidence-class primary
wiki promote answer.md --status draft
wiki rebuild
wiki lint
```

Subcommands run from anywhere inside the project — the CLI walks up to find
`.wiki`, like git finds `.git`.

Not on PATH yet? Call the zipapp directly: `python3 /path/to/repo/tools/wiki.pyz
init` (POSIX) or `python C:\path\to\repo\tools\wiki.pyz init` (Windows).

The launcher verifies the zipapp checksum before running; skip that check with
`WIKI_SKIP_CHECKSUM=1` (bash) / `$env:WIKI_SKIP_CHECKSUM=1` (PowerShell).

## Skills & CLI

### Skills

`skills/` holds three self-contained skill folders for coding agents.
They are a **bundle** — the skills reference `../wiki-docs/…`, so keep them as
siblings.

There are three skills. Each can operate independtly but all three require the `wiki-docs` folder.
- **`wiki-master`** — the entry-point how-to. **Use first / always.** Teaches an
  agent the whole model and routes it to the right skill and contracts for the
  task at hand. Point your agent here and it finds the rest.
- **`wiki-query`** — read-only retrieval. **Use when answering questions** from
  the wiki without changing anything: searching, reading pages, tracing the
  sources behind a claim. Constrains the agent to shared-lock, non-mutating
  commands.
- **`wiki-maintain`** — mutating operations. **Use when changing the wiki:**
  ingesting sources, promoting syntheses, retracting/superseding/purging
  sources, auditing, and resolving reviews. Enforces the rule that every change
  goes through the CLI.

And one supporting/reference documentation folder.
- **`wiki-docs`** — reference files - the shared contracts (`CONTRACT.md`, `QUERY-CONTRACT.md`, `MUTATION-CONTRACT.md`) the other three reference. **Not invoked directly;** it's the binding spec — data model, citation/claim syntax, source lifecycle, and the mutation guardrails — that the skills read.

To use them in another project, copy the four folders as-is into that project's
`.agents/skills/` (or `.claude/skills/`) — no edits needed:

```bash
cp -r skills/wiki-* /path/to/project/.agents/skills/
```

Point your agent at `wiki-master` first; it routes to the others.

Alternatively you can also set them up for global use by copying them to your home directory's agent skills folder.
```bash
# Define path to the repository
REPO_PATH="/path/to/your/llm-wiki-md-cli"

# Set the SKILLS_ROOT environment variable
export SKILLS_ROOT="$REPO_PATH/skills"  # or ~/.claude/skills

# Optional: Add this to your ~/.bashrc or ~/.zshrc to make it permanent
cp -r $REPO_PATH/skills/ $HOME/.agents/skills/  # or ~/.claude/skills
````

### CLI

For a one-page reference to every command — see
[`skills/wiki-docs/CHEATSHEET.md`](skills/wiki-docs/CHEATSHEET.md).
`wiki <command> --help` also prints usage for any command, and `--json` works on
all of them.

Read-only (shared lock): `query`, `search`, `read`, `sources-for`, `doctor`,
`metrics`, `schema check`, `reviews list/show`, `verify-diff`.

Mutating (exclusive lock): `init`, `ingest`, `promote`, `retract`, `supersede`,
`purge`, `rebuild`, `schema propose/migrate/restore`, `audit`,
`reviews resolve/defer/stale`, `recover`.

Exit codes are stable: `0` ok, `2` usage, `3` lock, `4` validation, `5`
integrity, `6` recovery-required, `7` not-initialised, `8` review-blocked.

### Recovery

Mutations are staged and journalled under `.wiki/ops/<id>/`. After a crash, the
next mutating command refuses (exit 6) until recovery runs. `wiki recover
--auto` performs only provably safe actions (finalise, abort, or roll back) by
comparing live file hashes to recorded before/after hashes. A **divergent**
operation (a file matching neither state, e.g. an external edit mid-operation)
requires an explicit choice: `--keep-live`, `--restore-before`, or
`--apply-after`.

## Acknowledgements

This project builds on two prior designs:

- **Andrej Karpathy's LLM wiki pattern** — persistent synthesis, immutable
  sources, structured wiki pages, and ingest/query/lint operations.
  https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- **nashsu's `llm_wiki`** — reliability mechanisms including crash recovery,
  deletion synchronisation, and a review queue.
  https://github.com/nashsu/llm_wiki

`llm-wiki-md-cli` retains the useful core of Karpathy's pattern without
requiring Obsidian or a standalone application, and borrows nashsu's reliability
mechanisms while omitting the desktop UI, permanent daemon, and
application-specific state layer.

## Contributing

The project is **not accepting pull requests or external contributions at this
time**. Bug reports and ideas via issues are welcome, but there is no commitment
to triage or respond. The software is provided as-is under the MIT License.

You are free to fork and build your own version. If you do, a credit back to
this project (`llm-wiki-md-cli` by [ankishraj](https://github.com/ankishraj)) is appreciated — though the MIT License only requires that you retain the copyright and license notice.

## License

MIT — see [`LICENSE`](LICENSE). Third-party components bundled in the built CLI
are listed in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
