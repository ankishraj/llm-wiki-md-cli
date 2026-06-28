---
name: wiki-master
description: >
  Operate the project-local, agent-maintained Markdown wiki via the `wiki` CLI.
  Use this whenever you need to read from or write to the project's canonical
  knowledge base — answering questions from stored knowledge, ingesting
  sources, synthesising claim-backed pages, retracting or superseding sources,
  auditing consistency, or recovering after an interrupted operation. This is
  the entry-point skill; it routes to the read-only (query) and mutating
  (maintain) sub-skills and explains the full workflow. All canonical changes
  go through the CLI — never edit files under wiki/ or .wiki/ directly.
contract_version: 1.0.0
---

# Wiki Skill (entry point)

This skill teaches you to operate the project wiki end to end. Read it first,
then read the contracts for whichever mode you are in (the `CONTRACT.md`,
`QUERY-CONTRACT.md`, and `MUTATION-CONTRACT.md` files live in the sibling
`wiki-docs` folder):

- **Reading / answering** → `../wiki-docs/CONTRACT.md` +
  `../wiki-docs/QUERY-CONTRACT.md` (see also the `wiki-query` skill)
- **Changing the wiki** → `../wiki-docs/CONTRACT.md` +
  `../wiki-docs/MUTATION-CONTRACT.md` (see also the `wiki-maintain` skill)
- **CLI cheatsheet** → `../wiki-docs/CONTRACT.md`

The contracts are binding. This file is the practical how-to that ties them
together.

> These four folders — `wiki-master`, `wiki-query`, `wiki-maintain`, and
> `wiki-docs` — are a bundle. Keep them as siblings in the same skills
> directory so the `../wiki-docs/…` references resolve. They are designed to be
> copied as-is into a project's `.agents/skills/` (or `.claude/skills/`) with no
> edits.

## Mental model (read this once)

The wiki stores three kinds of state, and the distinction drives every rule:

1. **Canonical knowledge** — `wiki/pages/`, `wiki/sources/`, `wiki/raw/`.
   This is the truth. You change it only through CLI mutation commands.
2. **Canonical operational state** — `.wiki/` (config, schema, `events.jsonl`,
   `ops/`, `reviews/`). The CLI owns this. You never hand-edit it.
3. **Disposable derived state** — `.wiki/cache/` and the generated indexes.
   Always rebuildable with `wiki rebuild`; losing it costs speed, never truth.

Two non-negotiables that catch most mistakes:

- **You never write canonical files directly.** Not with your editor, not with
  shell redirection. Every page, source, and event is produced by a `wiki`
  command. If there's no command for what you want, stop and ask the user.
- **The CLI is the integrity boundary.** It locks, validates, journals, and
  records provenance. Bypassing it silently breaks the guarantees the whole
  system exists to provide.

## Invoking the CLI

If the repo's `bin/` is on your PATH (recommended — see the project README's
"Put `wiki` on your PATH"), just call `wiki` from anywhere inside a project:

```bash
wiki <command> [options]                 # resolves the wiki by walking up to .wiki
```

If it isn't on PATH, call the launcher or the zipapp by path instead:

```bash
/path/to/repo/bin/wiki <command> ...      # launcher (verifies checksum)
python3 /path/to/repo/tools/wiki.pyz ...  # direct zipapp (any Python 3.11+)
```

The examples below use bare `wiki`.

Useful global habits:

- Add `--json` to any command when you need to parse the result programmatically
  rather than read it. Human text is the default.
- Mutating commands fail fast on lock contention; add `--wait <seconds>` to wait
  for another writer to finish instead of erroring.
- **Always check the exit code.** It is the contract, not the prose:

  | code | meaning | what you do |
  | --- | --- | --- |
  | 0 | success | continue |
  | 2 | usage error | fix your arguments |
  | 3 | lock contention | retry, or `--wait` |
  | 4 | validation failure | read the issues, fix the content |
  | 5 | integrity failure | something was edited outside the CLI; investigate |
  | 6 | recovery required | run `wiki recover --auto` first (see below) |
  | 7 | not initialised | `wiki init` |
  | 8 | review-blocked | resolve/defer the blocking review first |

## Before you do anything: orient

```bash
wiki doctor          # is the wiki healthy? schema valid? any partial ops?
```

If `doctor` reports an incomplete operation, or any command returns **exit 6**,
the wiki is in a partial state from an interrupted writer. Resolve that before
proceeding — see "Recovery" at the end. Don't try to work around it.

## Reading & answering (the query path)

Use only these read-only commands; they take a shared lock and never mutate.

```bash
wiki query "how do refresh tokens rotate?"   # lexical retrieval → page pointers
wiki search "rotation"                        # raw lexical search
wiki read wiki/pages/syntheses/token-rotation.md   # full page + its claims
wiki sources-for wiki/pages/syntheses/token-rotation.md  # backing sources
```

Answering discipline (full rules in `../wiki-docs/QUERY-CONTRACT.md`):

- `query` returns *pointers*, not prose. Open the pages it surfaces with `read`
  and compose the answer yourself, grounded in their claims and sources.
- Ground every factual statement in a cited source or a sourced claim. If
  retrieval finds nothing, say so — point at raw sources rather than inventing
  support.
- Prefer **active** sources. If the only support is retracted/superseded/purged,
  flag it instead of presenting it as settled.
- Distinguish a **draft** synthesis from a **stable** one. Never present a draft
  as established.
- Surface any open **blocking** review whose scope covers the topic — it means
  the area is contested.
- If you spot a contradiction or gap while reading, **report it; don't fix it
  from the query path.** Fixing is a maintain-mode action with user intent.

## Changing the wiki (the maintain path)

Every change is one of a small set of commands. The general loop is:
**check reviews → run the mutation → rebuild → lint → resolve any errors.**

### Ingest a source

Register a piece of evidence. The CLI hashes it, stores it content-addressed,
writes a descriptor, and journals the operation.

```bash
wiki ingest path/to/rfc.txt \
  --id source-rfc-tokens \
  --title "Token RFC" \
  --evidence-class primary        # canonical-project-artifact|primary|secondary|tertiary|generated|unknown
wiki rebuild                 # refresh derived indexes (ingest advises this)
```

Ingest registers provenance only. It does **not** write synthesis prose — that
is your job, via `promote`.

### Promote a synthesis (requires explicit user intent)

Author an answer file with frontmatter and at least one fenced claim block,
then promote it. Only do this when the **user has asked for it**.

````markdown
---
id: synthesis-token-rotation
type: synthesis
title: Token Rotation
summary: how the service rotates tokens
status: draft
updated_at: 2026-06-28
---

# Token Rotation

```claim
id: claim-token-001
status: supported
sources:
  - source-rfc-tokens#section-4
  - source-design-review#page-12
```
The service uses short-lived access tokens and rotating refresh tokens.
```/claim```
````

```bash
wiki promote answer.md --status draft     # or --status stable
wiki rebuild && wiki lint
```

Support thresholds the CLI enforces (don't fabricate sources to pass them):

- **draft** — ≥1 valid *active* source; no duplicate canonical id.
- **stable** — ≥2 independent active sources, **or** one
  `canonical-project-artifact`/accepted decision, **or** a single authoritative
  source only with `--approve` (when config allows).

If promotion is rejected (exit 4), report the reason. Don't weaken the claim
set to force it through.

### Retract / supersede / purge a source

```bash
wiki retract source-design-review --reason "withdrawn by author"
wiki supersede source-rfc-tokens-v1 source-rfc-tokens-v2
wiki purge source-leaked-doc --confirm      # exceptional; raw removed, tombstone kept
wiki rebuild && wiki lint
```

What to expect:

- **retract** preserves the raw blob, marks the descriptor retracted, and opens
  a **blocking review** for any claim that just lost its *sole active support*.
  Address those reviews — don't leave a `supported` claim with only inactive
  evidence (lint will error, exit 4).
- **supersede** records `old → new`. Recency wins only through this explicit
  command, never implicitly.
- **purge** is exceptional and needs `--confirm`. It deletes the raw blob but
  leaves a resolvable tombstone, so citations don't dangle.

### Contradiction & precedence policy

When a change would alter, contradict, or remove a claim:

- Never silently delete a conflicting claim. Higher-precedence evidence informs
  *priority*, not deletion.
- If sources genuinely conflict, **represent the disagreement**: mark the claim
  `disputed` and cite both sides, or open a review with `wiki audit`.
- Keep at least one active source behind every `supported` claim.

## Auditing & the review queue

`lint` is deterministic and can fail a commit. `audit` is the scoped,
semantic layer that records findings as **review items** rather than blocking.

```bash
wiki lint                              # deterministic checks; exit 4 on errors
wiki audit --changed-since <op-id>     # cheap, scoped audit
wiki audit --topic synthesis-token-rotation
wiki audit --source source-rfc-tokens
wiki audit --full                      # whole corpus (expensive)

wiki reviews list --state open --severity blocking
wiki reviews show <review-id>
wiki reviews resolve <review-id> --note "added second source"
wiki reviews defer  <review-id> --note "revisit after Q3"
wiki reviews stale                     # age out reviews whose area kept changing
```

Reviews are **scoped**: a blocking review blocks mutations to the affected page
or claim, not the whole wiki. Always check for blocking reviews intersecting
your target *before* you mutate it (`reviews list --state open --severity
blocking`), and surface them to the user.

## Schema evolution

The active page schema is pinned in `.wiki/schema.lock`. Schemas are immutable
once published; corrections create a new version.

```bash
wiki schema check                      # meta-validate the active schema
wiki schema list
wiki schema propose path/to/v2.json    # stage + meta-validate a new version
wiki schema migrate --to v2            # validates every page against v2, atomically
```

## Recovery (when a writer was interrupted)

Mutations are staged and journalled under `.wiki/ops/<id>/`. After a crash the
next mutating command refuses with **exit 6** until the wiki is made consistent.

```bash
wiki recover --auto
```

`--auto` performs only provably safe actions by comparing live file hashes to
the recorded before/after hashes: it finalises a fully-applied operation, aborts
one that never applied, or rolls back a partial one. A **divergent** operation —
a file matching neither the before nor the after state, e.g. something was
edited outside the CLI mid-operation — needs an explicit decision:

```bash
wiki recover <op-id> --restore-before   # discard the operation's changes
wiki recover <op-id> --apply-after       # force the intended end state
wiki recover <op-id> --keep-live         # accept the current on-disk state
```

Pick based on user intent. Never delete or hand-edit anything under `.wiki/ops/`.

## A complete worked session

```bash
wiki doctor                                   # 1. orient; ensure healthy
wiki ingest rfc.txt --id source-rfc --evidence-class primary
wiki ingest design.md --id source-design --evidence-class secondary
wiki rebuild                                  # 2. refresh indexes
# 3. author answer.md with a claim block citing both sources, then:
wiki promote answer.md --status draft         # (user asked for this)
wiki rebuild && wiki lint               # 4. expect 0 errors
wiki verify-diff                               # 5. canonical state matches journal
```

## Quick rules to never violate

- Don't write `wiki/` or `.wiki/` by hand — only via CLI commands.
- Don't ignore exit codes; treat 4/5/6/8 as work to finish, not noise.
- Don't promote without explicit user intent.
- Don't silently delete or override a conflicting claim — dispute or review it.
- Don't fabricate sources, hashes, or operation records to pass a gate. These
  are integrity controls operating in good faith, not a security boundary; if
  you can't do it legitimately through the CLI, escalate to the user.
