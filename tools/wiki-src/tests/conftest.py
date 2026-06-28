"""Shared pytest fixtures for the wiki CLI test suite."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

from wikicli.__main__ import build_parser, main


@pytest.fixture
def repo_dir(tmp_path, monkeypatch):
    """A temp directory that is the cwd, for running wiki commands against."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Invoke the CLI in-process, capturing stdout/stderr and exit code."""
    out, errbuf = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(errbuf):
        code = main(argv)
    return code, out.getvalue(), errbuf.getvalue()


@pytest.fixture
def cli():
    return run_cli
