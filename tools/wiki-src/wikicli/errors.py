"""Error types and exit codes for the wiki CLI.

Exit codes are stable and scriptable. CI and pre-commit hooks rely on them.

  0  success
  1  generic / unexpected error
  2  usage error (bad arguments)
  3  lock contention (wiki is locked)
  4  validation failure (schema / lint errors)
  5  integrity failure (hash mismatch, divergent state, tampering detected)
  6  recovery required (an unfinished operation blocks the command)
  7  not initialised (no .wiki directory)
  8  review-blocked (a blocking review prevents the mutation)
"""

from __future__ import annotations


class WikiError(Exception):
    """Base class for all CLI errors. Carries a stable exit code."""

    exit_code = 1

    def __init__(self, message: str, *, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class UsageError(WikiError):
    exit_code = 2


class LockError(WikiError):
    exit_code = 3


class ValidationError(WikiError):
    exit_code = 4

    def __init__(self, message: str, *, errors: list[str] | None = None, detail: str | None = None):
        super().__init__(message, detail=detail)
        self.errors = errors or []


class IntegrityError(WikiError):
    exit_code = 5


class RecoveryRequired(WikiError):
    exit_code = 6

    def __init__(self, message: str, *, operation_id: str | None = None, detail: str | None = None):
        super().__init__(message, detail=detail)
        self.operation_id = operation_id


class NotInitialised(WikiError):
    exit_code = 7


class ReviewBlocked(WikiError):
    exit_code = 8

    def __init__(self, message: str, *, review_ids: list[str] | None = None, detail: str | None = None):
        super().__init__(message, detail=detail)
        self.review_ids = review_ids or []
