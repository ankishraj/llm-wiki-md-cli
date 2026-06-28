---
name: wiki-maintain
description: >
  Maintain the project wiki: ingest sources, promote syntheses, retract /
  supersede / purge sources, run audits and resolve reviews. Use when the user
  asks you to change the canonical knowledge base. All changes go through the
  wiki CLI; never edit canonical files directly.
contract_version: 1.0.0
---

# Wiki Maintain Skill

Read `../wiki-docs/CONTRACT.md`, `../wiki-docs/MUTATION-CONTRACT.md`, `../wiki-docs/CHEATSHEET.md` before acting.

- Use only mutation commands through the CLI; never directly edit canonical
  wiki state or anything under `.wiki/ops/`.
- Before mutating, check for open blocking reviews whose scope intersects your
  target and surface them.
- Respect precedence and contradiction policy: represent conflicts (dispute or
  review), never silently delete a claim; recency wins only via explicit
  `wiki supersede`.
- Promote only on explicit user intent, honouring the CLI's support thresholds.
- After source-affecting changes, run `wiki rebuild` then `wiki lint`, and
  resolve any errors.
- On recovery-required (exit 6), run `wiki recover --auto`; for a divergent
  operation pick `--keep-live` / `--restore-before` / `--apply-after` per user
  intent.
