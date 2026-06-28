# Wiki Shared Contract

**Contract version: 1.0.0** (versioned alongside the schema; both skills declare
the version they support so mismatches can be detected.)

This is the single shared data model for both the query and maintain skills.
Neither skill duplicates it. Read this file plus the one role-specific contract
for your skill.

## What this wiki is

A project-local, agent-maintained Markdown knowledge base that lives beside the
code. Markdown is **canonical**. Indexes, manifests, backlinks, claim indexes
and any embeddings are **disposable derived state**, always rebuildable with
`wiki rebuild`. All canonical mutation flows through the `wiki` CLI — never by
editing canonical files directly.

Three kinds of state:

- **Canonical knowledge** — `wiki/` (pages, source descriptors, raw blobs).
- **Canonical operational state** — `.wiki/` (config, schema, events, ops,
  reviews).
- **Disposable derived state** — `.wiki/cache/` and the generated indexes.

## Paths

```
wiki/
  index.md                      generated routing index; never hand-edit
  pages/
    topics/      <slug>.md       type: topic
    entities/    <slug>.md       type: entity
    decisions/   <slug>.md       type: decision
    syntheses/   <slug>.md       type: synthesis
  sources/       <source-id>.md  source descriptors (canonical provenance)
  raw/sha256/<prefix>/<hash>.<ext>   content-addressed raw blobs (immutable)
.wiki/
  config.toml      schema.lock     schemas/   migrations/
  events.jsonl     ops/            reviews/   eval/   cache/
```

A page's `type` must match its directory (enforced by lint). Generated
per-category indexes are named `_index.md` and are never authored by hand.

## Page taxonomy

`topic`, `entity`, `decision`, `synthesis` (plus `note`). Frontmatter is YAML
delimited by `---`. Required keys: `id`, `type`, `title`, `summary`, `status`,
`updated_at`. The `id` is `<type>-<slug>` (e.g. `synthesis-token-rotation`).

`synthesis` and `decision` pages **must** contain at least one claim block.

## Citation syntax

In prose, cite a source with `[[source-<slug>]]` or `[[source-<slug>#fragment]]`.
Link another page with `[[<type>-<slug>]]`. Citations to nonexistent sources are
lint errors; citations to retracted/superseded/purged sources are warnings.

## Claim format (fenced, greppable)

Claims use a fenced ```` ```claim ```` block holding YAML metadata, followed by
the claim prose, closed by ```` ```/claim``` ````:

````
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

Claim `status` is one of: `supported`, `disputed`, `unsupported`, `superseded`,
`draft`. A `supported` or `disputed` claim must list at least one source. A
`supported` claim whose only evidence is inactive (retracted/superseded/purged)
is a lint error.

## Source states

`active` -> `retracted` (raw preserved) -> `superseded` (replaced by another) ->
`purged` (raw removed, tombstone retained and still resolvable). Raw blobs are
content-addressed and immutable; never edit anything under `wiki/raw/`.

Evidence classes (precedence order): `canonical-project-artifact`, `primary`,
`secondary`, `tertiary`, `generated`, `unknown`. Precedence informs review
priority and recommendations; it never silently deletes conflicting claims.

## Schema

The active page schema version is recorded in `.wiki/schema.lock`. Schemas are
immutable once published; corrections create a new version via
`wiki schema propose` + `wiki schema migrate --to vN`. Validate with
`wiki schema check`.

## CLI invocation rules

- Run every wiki action through the `wiki` wrapper (or `python wiki.pyz`).
- Read-only commands take a shared lock; mutating commands take an exclusive
  lock. Use `--wait <seconds>` to wait for contention; default is fail-fast.
- Commands accept `--json` for machine-readable output.
- Exit codes are stable: 0 ok, 2 usage, 3 lock, 4 validation, 5 integrity,
  6 recovery-required, 7 not-initialised, 8 review-blocked.
- If a command reports recovery-required (6), run `wiki recover --auto` (and,
  for a divergent operation, choose `--keep-live` / `--restore-before` /
  `--apply-after`) before retrying.
