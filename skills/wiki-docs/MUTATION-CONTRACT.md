# Wiki Mutation Contract (maintain)

**Contract version: 1.0.0**

This is the primary written constraint on agent mutation behaviour. Read
`CONTRACT.md` first for the data model. Every clause below is binding on the
maintain skill.

## 1. All canonical change goes through a `wiki` mutation command

The agent **never writes canonical files directly** — not pages under
`wiki/pages/`, not source descriptors under `wiki/sources/`, not anything under
`wiki/raw/`, not `.wiki/events.jsonl`, `.wiki/schema.lock`, or the schema files.
Every canonical change is made by invoking a CLI mutation command:

| Intent | Command |
| --- | --- |
| Register a source | `wiki ingest <file> [--id ...] [--evidence-class ...]` |
| Publish/answer a synthesis | `wiki promote <answer.md> --status draft\|stable` |
| Withdraw a source (keep raw) | `wiki retract <source-id> --reason ...` |
| Replace a source | `wiki supersede <old-id> <new-id>` |
| Remove raw (keep tombstone) | `wiki purge <source-id> --confirm` |
| Regenerate derived state | `wiki rebuild` |
| Evolve the schema | `wiki schema propose ...` then `wiki schema migrate --to vN` |
| Record review findings | `wiki audit --changed-since\|--topic\|--source\|--full` |
| Resolve a review | `wiki reviews resolve\|defer <review-id>` |

If a needed change has no command, stop and raise it with the user. Do not work
around the CLI.

## 2. Staged operations live only under `.wiki/ops/<operation-id>/`

Mutations are staged, journalled and recoverable. The CLI writes the request,
plan (with before/after hashes), backups and staged content under
`.wiki/ops/<operation-id>/`, applies changes with atomic rename, then appends
events. The agent must never hand-create, edit, or delete anything under
`.wiki/ops/`. If a command reports **recovery-required (exit 6)**, run
`wiki recover --auto`; for a **divergent** operation choose exactly one of
`--keep-live`, `--restore-before`, `--apply-after` based on user intent. Never
attempt to "clean up" an operation directory manually.

## 3. Surface blocking reviews before related mutations

Before mutating a page, claim, or source, check for open **blocking** reviews
whose scope intersects what you are about to change (`wiki reviews list
--state open --severity blocking`). A blocking review is **scoped**: it blocks
mutations to the affected page or claim, not the whole wiki. If a blocking
review covers your target, surface it to the user and resolve or defer it
(`wiki reviews resolve|defer`) before proceeding. Do not route around a blocking
review by editing a different file.

## 4. Precedence and contradiction policy govern claim changes (§10–§11)

When a proposed change would alter, contradict, or remove a claim:

- Do not silently delete a conflicting claim. Higher-precedence evidence
  (see evidence classes in `CONTRACT.md`) informs *priority*, not deletion.
- If sources genuinely conflict, represent the disagreement: mark the claim
  `disputed` and cite both sides, or open a review with `wiki audit` for a
  human/agent decision. Recency wins only through an explicit
  `wiki supersede`, never implicitly.
- A `supported` claim must retain at least one **active** supporting source. If
  a retraction would leave a claim unsupported, the CLI opens a blocking review;
  address it rather than forcing the claim to stay `supported`.

## 5. Promotion requires explicit user intent (§12)

Never promote a synthesis to `draft` or `stable` on your own initiative.
Promotion happens only when the user asks for it. Respect the support
thresholds the CLI enforces:

- **draft** — at least one valid, active source; no duplicate canonical id.
- **stable** — multiple independent active sources, or one
  `canonical-project-artifact` / accepted decision, or a single authoritative
  source only with explicit `--approve` (when config permits).

If the CLI rejects a promotion (exit 4), report the reason; do not weaken the
claim set or fabricate sources to get past the gate.

## 6. After mutating, refresh derived state

Source-affecting mutations advise a rebuild. Run `wiki rebuild` after ingest,
retract, supersede, purge, or promote so indexes, backlinks and the claim index
reflect the new state. Then run `wiki lint` and treat any error (exit 4) as
work to finish, not noise to suppress.

## 7. Integrity, not security

These controls detect mistakes and drift; they are not a security boundary
against a determined adversary. Operate in good faith: do not fabricate
operation records, event entries, or hashes to make `verify-diff` pass. If you
cannot make a change legitimately through the CLI, escalate to the user.
