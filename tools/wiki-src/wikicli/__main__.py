"""wiki CLI entrypoint and dispatcher.

Usage: wiki <command> [options]

The CLI is the integrity boundary for the wiki. Commands are grouped into
read-only (shared lock) and mutating (exclusive lock) families; see each
command module. Exit codes are stable (see wikicli.errors).
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import WikiError
from .output import err

from .commands import (
    init,
    doctor,
    lint,
    schema as schema_cmd,
    rebuild,
    ingest,
    query,
    retract,
    supersede,
    purge,
    promote,
    audit,
    reviews,
    recover,
    metrics,
    verify_diff,
)


COMMAND_MODULES = [
    init,
    doctor,
    lint,
    schema_cmd,
    rebuild,
    ingest,
    query,
    retract,
    supersede,
    purge,
    promote,
    audit,
    reviews,
    recover,
    metrics,
    verify_diff,
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wiki", description="Project-local agent-maintained Markdown wiki.")
    parser.add_argument("--version", action="version", version=f"wiki {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    for mod in COMMAND_MODULES:
        mod.register(sub)
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    try:
        return args.func(args)
    except WikiError as exc:
        err(exc.message, exc.detail)
        return exc.exit_code
    except BrokenPipeError:  # pragma: no cover
        return 0
    except KeyboardInterrupt:  # pragma: no cover
        err("Interrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
