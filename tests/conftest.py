import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orch import config
from orch.board import Board
from orch.events import Log

CARD = """---
title: Add thing
area: backend
attempts: 0
---
# Add thing

## Goal
Add a thing.

## Acceptance criteria
- [ ] thing() returns 1

## Out of scope
- nothing

## Plan

## Tasks

## Blockers / questions

## Status log
"""


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    sh(p, "git", "init", "-q", "-b", "main")
    sh(p, "git", "config", "user.email", "t@t")
    sh(p, "git", "config", "user.name", "t")
    (p / ".gitignore").write_text("board/*/*.md\nboard/_log.md\n.orchestrator/\n", encoding="utf-8")
    (p / "memory").mkdir()
    (p / "memory" / "backend.md").write_text("# m\n", encoding="utf-8")
    Board(p).ensure()
    sh(p, "git", "add", "-A")
    sh(p, "git", "commit", "-qm", "init")
    return p


@pytest.fixture
def cfg():
    c = config.load(Path("."))
    c["ci"] = f'"{sys.executable}" -c "pass"'
    c["reviewers"] = [{"name": "qa", "kind": "claude", "agent": "qa"}, {"name": "cross", "kind": "agy", "model": "m"}]
    return c


@pytest.fixture
def log(project):
    return Log(project, echo=False)


def add_card(project, name="001-thing", text=CARD):
    f = project / "board" / "backlog" / f"{name}.md"
    f.write_text(text, encoding="utf-8")
    return f
