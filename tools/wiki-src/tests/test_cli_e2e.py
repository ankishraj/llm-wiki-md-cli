"""End-to-end CLI tests exercising the full lifecycle in-process."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import run_cli


def _init(repo_dir):
    code, out, err = run_cli(["init"])
    assert code == 0, err


def _write_source(tmp: Path, name: str, content: str) -> str:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return str(p)


SYNTH = """---
id: synthesis-token-rotation
type: synthesis
title: Token Rotation
summary: how tokens rotate
status: draft
updated_at: 2026-06-28
---

# Token Rotation

```claim
id: claim-token-001
status: supported
sources:
  - source-rfc-tokens
  - source-design-review
```
Short-lived access tokens and rotating refresh tokens.
```/claim```
"""


def test_init_doctor(repo_dir):
    _init(repo_dir)
    code, out, err = run_cli(["doctor", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["ok"] is True


def test_ingest_promote_lint_rebuild(repo_dir, tmp_path):
    _init(repo_dir)
    s1 = _write_source(tmp_path, "rfc.txt", "rfc content")
    s2 = _write_source(tmp_path, "design.txt", "design content")
    assert run_cli(["ingest", s1, "--id", "source-rfc-tokens", "--evidence-class", "primary"])[0] == 0
    assert run_cli(["ingest", s2, "--id", "source-design-review", "--evidence-class", "secondary"])[0] == 0

    answer = tmp_path / "answer.md"
    answer.write_text(SYNTH, encoding="utf-8")
    assert run_cli(["promote", str(answer), "--status", "draft"])[0] == 0
    assert run_cli(["rebuild"])[0] == 0

    code, out, err = run_cli(["lint", "--json"])
    data = json.loads(out)
    assert data["error_count"] == 0


def test_retract_opens_blocking_review_and_lint_errors(repo_dir, tmp_path):
    _init(repo_dir)
    s1 = _write_source(tmp_path, "rfc.txt", "rfc content")
    s2 = _write_source(tmp_path, "design.txt", "design content")
    run_cli(["ingest", s1, "--id", "source-rfc-tokens", "--evidence-class", "primary"])
    run_cli(["ingest", s2, "--id", "source-design-review", "--evidence-class", "secondary"])
    answer = tmp_path / "answer.md"
    answer.write_text(SYNTH, encoding="utf-8")
    run_cli(["promote", str(answer), "--status", "draft"])
    run_cli(["rebuild"])

    # Retract one source: claim still has another active source -> no review.
    assert run_cli(["retract", "source-design-review", "--reason", "x"])[0] == 0
    code, out, _ = run_cli(["reviews", "list", "--json"])
    assert json.loads(out)["reviews"] == []

    # Retract the second: claim now unsupported -> blocking review + lint error.
    assert run_cli(["retract", "source-rfc-tokens", "--reason", "y"])[0] == 0
    code, out, _ = run_cli(["reviews", "list", "--state", "open", "--severity", "blocking", "--json"])
    reviews = json.loads(out)["reviews"]
    assert len(reviews) == 1
    assert "claim-token-001" in reviews[0]["scope"]

    code, out, _ = run_cli(["lint", "--json"])
    assert code == 4
    data = json.loads(out)
    assert any(i["code"] == "claim-support" for i in data["issues"])


def test_recovery_required_blocks_mutation(repo_dir, tmp_path):
    _init(repo_dir)
    # Manufacture an incomplete (applied, not committed) operation.
    from wikicli.core.paths import Repo
    from wikicli.core.operations import Operation
    repo = Repo(repo_dir)
    op = Operation.create(repo, "ingest", {})
    op.stage_write("wiki/pages/topics/ghost.md",
                   "---\nid: topic-ghost\ntype: topic\ntitle: G\nsummary: s\nstatus: active\nupdated_at: 2026-06-28\n---\nbody\n")
    op.prepare()
    op.apply()  # leaves it incomplete

    # A mutating command must refuse with exit 6.
    code, out, err = run_cli(["rebuild"])
    assert code == 6

    # recover --auto finalises it, then rebuild works.
    assert run_cli(["recover", "--auto"])[0] == 0
    assert run_cli(["rebuild"])[0] == 0


def test_verify_diff_detects_untracked_edit(repo_dir, tmp_path):
    _init(repo_dir)
    s1 = _write_source(tmp_path, "rfc.txt", "rfc content")
    run_cli(["ingest", s1, "--id", "source-rfc-tokens", "--evidence-class", "primary"])
    # Hand-edit the descriptor (forbidden) -> verify-diff should flag a mismatch.
    desc = repo_dir / "wiki/sources/source-rfc-tokens.md"
    desc.write_text(desc.read_text() + "\n<!-- tampered -->\n", encoding="utf-8")
    code, out, err = run_cli(["verify-diff", "--json"])
    assert code == 5
    assert json.loads(out)["ok"] is False


def test_schema_migrate(repo_dir, tmp_path):
    _init(repo_dir)
    v2 = json.loads((repo_dir / ".wiki/schemas/v1.json").read_text())
    v2["schemaVersion"] = "v2"
    v2["properties"]["owner"] = {"type": "string"}
    proposal = tmp_path / "v2.json"
    proposal.write_text(json.dumps(v2), encoding="utf-8")
    assert run_cli(["schema", "propose", str(proposal)])[0] == 0
    assert run_cli(["schema", "migrate", "--to", "v2"])[0] == 0
    code, out, _ = run_cli(["schema", "list", "--json"])
    data = json.loads(out)
    assert data["active"] == "v2"
