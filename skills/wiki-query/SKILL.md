---
name: wiki-query
description: >
  Read-only retrieval from the project wiki. Use when you need to answer a
  question from the project's canonical knowledge base (topics, entities,
  decisions, syntheses) and their cited sources, without changing anything.
contract_version: 1.0.0
---

# Wiki Query Skill

Read `../wiki-docs/CONTRACT.md`, `../wiki-docs/QUERY-CONTRACT.md`, `../wiki-docs/CHEATSHEET.md` before acting.

- Use only shared-lock / read-only CLI commands (`wiki query`, `wiki search`,
  `wiki read`, `wiki sources-for`, and inspection commands).
- Never modify the wiki or promote results.
- Ground answers in cited sources or sourced claims; prefer active sources;
  flag drafts, disputed claims, and any open blocking reviews in the area.
- If you spot a problem, report it for the maintain skill rather than fixing it.
