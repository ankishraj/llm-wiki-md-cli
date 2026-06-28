"""Output helpers. Commands support `--json` for machine-readable output (used
by agents and CI); otherwise they print concise human text."""

from __future__ import annotations

import json
import sys


def emit(data: dict, *, as_json: bool, human: str | None = None):
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif human is not None:
        print(human)


def err(message: str, detail: str | None = None):
    print(message, file=sys.stderr)
    if detail:
        print(detail, file=sys.stderr)


def info(message: str):
    print(message)
