# Wiki Query Contract (read-only)

**Contract version: 1.0.0**

This constrains the **query** skill. Read `CONTRACT.md` first for the data model.

## Hard constraints

- Use only **read-only / shared-lock** commands. Never mutate, never promote.
- Never write to `wiki/` or `.wiki/`. Never edit canonical files or derived
  caches by hand.
- Do not run `ingest`, `promote`, `retract`, `supersede`, `purge`, `rebuild`,
  `schema migrate`, `audit`, or any `reviews` subcommand that transitions state.

## Allowed commands

- `wiki query "<question>"` — lexical retrieval of relevant pages. Returns
  pointers; you compose the answer from the pages it surfaces.
- `wiki search "<term>"` — raw lexical search.
- `wiki read <path>` — read a page with its claims and sources.
- `wiki sources-for <path>` — list the sources backing a page.
- `wiki doctor`, `wiki metrics`, `wiki schema check`, `wiki reviews list/show`,
  `wiki verify-diff` — non-mutating inspection.

## Answering discipline

- Ground every factual statement in a cited source or a claim that carries
  sources. If retrieval returns nothing, say so and point at the raw sources
  rather than inventing support.
- Prefer `active` sources. If the only support is retracted/superseded/purged,
  flag that explicitly rather than presenting it as settled.
- Surface relevant **open blocking reviews** when you answer about an area they
  scope, so the reader knows the synthesis is contested.
- Never present a `draft` synthesis as established. Distinguish draft from
  stable.

## When you find a problem

If you notice a contradiction, missing source, or stale synthesis, do **not**
fix it from the query skill. Report it. A maintainer (the maintain skill, with
user intent) handles mutations and can open a review with `wiki audit`.
