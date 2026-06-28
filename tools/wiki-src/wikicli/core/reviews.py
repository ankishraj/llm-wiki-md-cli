"""Review queue lifecycle (plan section 15).

Review items are JSON files under .wiki/reviews/. They are never silently
deleted; they transition between states: open -> resolved | deferred |
superseded | stale.

Severity:
  blocking  prevents mutations to the affected page or claim (SCOPED)
  warning   surfaced during related operations
  advisory  informational only

Staleness (PINNED): `stale_after_operations` counts committed operations whose
scope intersects the review's scope, measured from created_seq -- NOT total
repository operations. A review ages only as its subject area changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .events import (
    EV_OPERATION_COMMITTED,
    EV_OPERATION_ROLLED_BACK,
    EV_SOURCE_RETRACTED,
    EV_SOURCE_SUPERSEDED,
    EventLog,
)
from .ids import new_ulid, now_iso
from .paths import Repo

STATE_OPEN = "open"
STATE_RESOLVED = "resolved"
STATE_DEFERRED = "deferred"
STATE_SUPERSEDED = "superseded"
STATE_STALE = "stale"

SEV_BLOCKING = "blocking"
SEV_WARNING = "warning"
SEV_ADVISORY = "advisory"
SEVERITIES = (SEV_BLOCKING, SEV_WARNING, SEV_ADVISORY)


@dataclass
class Review:
    review_id: str
    state: str
    severity: str
    scope: list[str]
    reason: str
    created_seq: int
    stale_after_operations: int
    kind: str = "general"
    created_at: str = ""
    resolved_at: str | None = None
    resolution: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            "review_id": self.review_id,
            "state": self.state,
            "severity": self.severity,
            "scope": self.scope,
            "reason": self.reason,
            "kind": self.kind,
            "created_seq": self.created_seq,
            "stale_after_operations": self.stale_after_operations,
            "created_at": self.created_at,
        }
        if self.resolved_at:
            d["resolved_at"] = self.resolved_at
        if self.resolution:
            d["resolution"] = self.resolution
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Review":
        return cls(
            review_id=d["review_id"],
            state=d.get("state", STATE_OPEN),
            severity=d.get("severity", SEV_WARNING),
            scope=list(d.get("scope", [])),
            reason=d.get("reason", ""),
            created_seq=int(d.get("created_seq", 0)),
            stale_after_operations=int(d.get("stale_after_operations", 20)),
            kind=d.get("kind", "general"),
            created_at=d.get("created_at", ""),
            resolved_at=d.get("resolved_at"),
            resolution=d.get("resolution"),
            extra=d.get("extra", {}),
        )


class ReviewStore:
    def __init__(self, repo: Repo):
        self.repo = repo

    def _path(self, review_id: str) -> Path:
        return self.repo.review_path(review_id)

    def create(
        self,
        *,
        severity: str,
        scope: list[str],
        reason: str,
        created_seq: int,
        kind: str = "general",
        stale_after_operations: int = 20,
        extra: dict | None = None,
    ) -> Review:
        review_id = "review-" + new_ulid()
        review = Review(
            review_id=review_id,
            state=STATE_OPEN,
            severity=severity,
            scope=list(scope),
            reason=reason,
            created_seq=created_seq,
            stale_after_operations=stale_after_operations,
            kind=kind,
            created_at=now_iso(),
            extra=extra or {},
        )
        self.save(review)
        return review

    def save(self, review: Review):
        self.repo.reviews.mkdir(parents=True, exist_ok=True)
        self._path(review.review_id).write_text(
            json.dumps(review.as_dict(), indent=2), encoding="utf-8"
        )

    def get(self, review_id: str) -> Review | None:
        p = self._path(review_id)
        if not p.exists():
            return None
        return Review.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def all(self) -> list[Review]:
        if not self.repo.reviews.is_dir():
            return []
        out = []
        for p in sorted(self.repo.reviews.glob("review-*.json")):
            try:
                out.append(Review.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return out

    def open_reviews(self) -> list[Review]:
        return [r for r in self.all() if r.state == STATE_OPEN]

    def blocking_for_scope(self, scope_items: list[str]) -> list[Review]:
        """Open, blocking reviews whose scope intersects the given items."""
        target = set(scope_items)
        out = []
        for r in self.open_reviews():
            if r.severity == SEV_BLOCKING and (set(r.scope) & target):
                out.append(r)
        return out

    def transition(self, review: Review, new_state: str, resolution: str | None = None):
        review.state = new_state
        if new_state in (STATE_RESOLVED, STATE_SUPERSEDED, STATE_STALE, STATE_DEFERRED):
            review.resolved_at = now_iso()
        if resolution:
            review.resolution = resolution
        self.save(review)


# -- staleness evaluation ---------------------------------------------------

def _event_scope(event: dict) -> set[str]:
    """Best-effort scope of a committed/compensating event: changed files plus
    any affected claim/source identifiers recorded on the event."""
    scope: set[str] = set()
    for f in event.get("files_changed", []) or []:
        scope.add(f)
    for c in event.get("claims_changed", []) or []:
        scope.add(c)
    if event.get("source_id"):
        scope.add(event["source_id"])
    for s in event.get("affected_claims", []) or []:
        scope.add(s)
    return scope


def count_scope_intersecting_ops(log: EventLog, review: Review) -> int:
    """Count committed operations after created_seq whose scope intersects the
    review's scope. This is the PINNED staleness metric."""
    review_scope = set(review.scope)
    if not review_scope:
        return 0
    count = 0
    relevant_types = {
        EV_OPERATION_COMMITTED,
        EV_OPERATION_ROLLED_BACK,
        EV_SOURCE_RETRACTED,
        EV_SOURCE_SUPERSEDED,
    }
    for event in log.events_after_seq(review.created_seq):
        if event.get("type") not in relevant_types:
            continue
        if _event_scope(event) & review_scope:
            count += 1
    return count


def evaluate_staleness(repo: Repo) -> list[Review]:
    """Transition open reviews to stale when their scope-intersecting op count
    reaches the threshold. Returns the reviews that became stale."""
    store = ReviewStore(repo)
    log = EventLog(repo.events)
    became_stale = []
    for review in store.open_reviews():
        n = count_scope_intersecting_ops(log, review)
        if n >= review.stale_after_operations:
            store.transition(review, STATE_STALE, resolution="auto-stale")
            became_stale.append(review)
    return became_stale
