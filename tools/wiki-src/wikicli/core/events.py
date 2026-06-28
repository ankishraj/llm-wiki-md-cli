"""Append-only event log (plan section 3).

events.jsonl is strictly append-only. Existing events are never edited or
removed. Each event carries:

  seq          monotonic integer, allocated while holding the exclusive lock
  event_id     ULID-style unique id
  operation_id ULID-style id of the owning operation (may be shared)
  type         event type string
  at           ISO 8601 timestamp

Ordering is determined by `seq`, not by lexicographic id ordering.

Rollbacks/retractions/supersessions APPEND compensating events; they never
erase history. `--changed-since <operation-id>` resolves to the commit
event's seq and inspects effective changes after it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .ids import new_ulid, now_iso

# Canonical event types.
EV_INITIALISED = "initialised"
EV_OPERATION_COMMITTED = "operation_committed"
EV_OPERATION_ROLLED_BACK = "operation_rolled_back"
EV_OPERATION_ABORTED = "operation_aborted"
EV_SOURCE_INGESTED = "source_ingested"
EV_SOURCE_RETRACTED = "source_retracted"
EV_SOURCE_SUPERSEDED = "source_superseded"
EV_SOURCE_PURGED = "source_purged"
EV_SCHEMA_MIGRATED = "schema_migrated"
EV_PAGE_PROMOTED = "page_promoted"
EV_REVIEW_OPENED = "review_opened"
EV_REVIEW_RESOLVED = "review_resolved"
EV_DERIVED_REBUILT = "derived_rebuilt"


class EventLog:
    """Reader/appender for events.jsonl.

    All append() calls MUST be made while holding the exclusive repository
    lock; seq allocation is not otherwise safe against concurrent writers.
    """

    def __init__(self, path: Path):
        self.path = path

    # -- reading ------------------------------------------------------------

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        events: list[dict] = []
        for line_no, raw in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                # Surface malformed event records to lint rather than crashing.
                events.append({"__malformed__": True, "line": line_no, "raw": raw, "error": str(exc)})
        return events

    def valid_events(self) -> list[dict]:
        return [e for e in self.read_all() if not e.get("__malformed__")]

    def malformed(self) -> list[dict]:
        return [e for e in self.read_all() if e.get("__malformed__")]

    def max_seq(self) -> int:
        seqs = [int(e["seq"]) for e in self.valid_events() if "seq" in e]
        return max(seqs) if seqs else 0

    def next_seq(self) -> int:
        return self.max_seq() + 1

    # -- writing ------------------------------------------------------------

    def append(self, type: str, operation_id: str, **fields) -> dict:
        """Append a single event, allocating the next seq. Caller must hold
        the exclusive lock."""
        event = {
            "seq": self.next_seq(),
            "event_id": new_ulid(),
            "operation_id": operation_id,
            "type": type,
            "at": now_iso(),
        }
        event.update(fields)
        self._append_raw(event)
        return event

    def append_many(self, events: list[dict]) -> list[dict]:
        """Append several events atomically with consecutive seqs."""
        seq = self.next_seq()
        written = []
        lines = []
        for partial in events:
            event = {
                "seq": seq,
                "event_id": new_ulid(),
                "at": now_iso(),
            }
            event.update(partial)
            lines.append(json.dumps(event, ensure_ascii=False))
            written.append(event)
            seq += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        return written

    def _append_raw(self, event: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # -- queries over history ----------------------------------------------

    def commit_seq_for_operation(self, operation_id: str) -> int | None:
        for e in self.valid_events():
            if e.get("operation_id") == operation_id and e.get("type") == EV_OPERATION_COMMITTED:
                return int(e["seq"])
        return None

    def events_after_seq(self, seq: int) -> list[dict]:
        return [e for e in self.valid_events() if int(e.get("seq", -1)) > seq]
