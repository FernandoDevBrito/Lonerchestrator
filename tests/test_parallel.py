"""Cards worked on at the same time, each in its own git worktree, merged one at a time."""
import json
import subprocess
import sys
from pathlib import Path

from conftest import add_card, sh
from test_anyai import mine, records  # noqa: F401  (the fixture: config with a fake third-party AI in every role)

from orch.agents import Runner
from orch.board import Board, Card
from orch.parallel import Parallel


def test_two_cards_run_together_and_both_merge(project, mine, log):  # noqa: F811
    cfg, calls = mine
    cfg["parallel"] = 2
    add_card(project, "001-a")
    add_card(project, "002-b")
    assert Parallel(project, cfg, log, Runner(project, cfg, log)).run() == 0
    assert sorted(c.id for c in Board(project).cards("done")) == ["001-a", "002-b"]
    assert (project / "001-a.py").exists() and (project / "002-b.py").exists()          # both merged into main
    built = [r for r in records(calls) if "built" in r]
    assert len({b["cwd"] for b in built}) == 2 and all(".orchestrator" in b["cwd"] for b in built)   # each in its own worktree
    a, b = sorted(built, key=lambda x: x["t0"])
    assert b["t0"] < a["t1"]                                                              # they really overlapped in time
    assert subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True).stdout.strip() == ""
    assert subprocess.run(["git", "branch", "--list", "card/*"], cwd=project, capture_output=True, text=True).stdout.strip() == ""
    assert not any((project / ".orchestrator" / "worktrees").glob("*"))                  # worktrees removed
    state = json.loads((project / ".orchestrator" / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "idle" and state["active"] == {}


def test_card_that_finds_a_moved_base_merges_it_and_reruns_ci(project, mine, log):  # noqa: F811
    cfg, _ = mine
    cfg["parallel"] = 2
    # the second card touches the same file as the first: git merges them cleanly only if the base is merged in first
    (project / "shared.txt").write_text("a\n\nb\n", encoding="utf-8")
    sh(project, "git", "add", "-A")
    sh(project, "git", "commit", "-qm", "shared")
    add_card(project, "001-a")
    add_card(project, "002-b")
    assert Parallel(project, cfg, log, Runner(project, cfg, log)).run() == 0
    assert len(Board(project).cards("done")) == 2


def test_blocked_card_keeps_its_work_and_does_not_stop_the_other(project, mine, log):  # noqa: F811
    cfg, _ = mine
    cfg["parallel"] = 2
    cfg["ci"] = f'"{sys.executable}" -c "import os,sys; sys.exit(1 if os.path.exists(\'002-b.py\') else 0)"'
    cfg["max_attempts"] = 1
    add_card(project, "001-a")
    add_card(project, "002-b")
    Parallel(project, cfg, log, Runner(project, cfg, log)).run()
    assert [c.id for c in Board(project).cards("done")] == ["001-a"]
    assert [c.id for c in Board(project).cards("blocked")] == ["002-b"]
    assert not (project / "002-b.py").exists()                                           # never reached main


def test_depends_waits_for_the_other_card(project):
    add_card(project, "001-a")
    f = add_card(project, "002-b")
    f.write_text(f.read_text(encoding="utf-8").replace("area: backend", "area: backend\ndepends: 001-a"), encoding="utf-8")
    b = Board(project)
    c2 = Card(f)
    assert not b.ready(c2)
    Card(project / "board" / "backlog" / "001-a.md").move("done")
    assert b.ready(c2) and Path(f).exists()
