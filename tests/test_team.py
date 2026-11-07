"""Several builders on one card: tasks grouped by the files they declare, parts built in separate worktrees, merged, safe fallback."""
import json
import subprocess

from conftest import add_card
from test_anyai import mine  # noqa: F401

from orch import groups
from orch.agents import Runner
from orch.board import Board
from orch.pipeline import Pipeline


def test_groups_split_by_files_and_refuse_when_unsure():
    t = "- [ ] a [files: a.py]\n- [ ] b [files: b.py, tests/b.py]\n- [ ] a2 [files: a.py]\n"
    g = groups.split(t, 3)
    assert len(g) == 2 and sorted(len(x[0]) for x in g) == [1, 2]                  # a and a2 share a file -> same group
    assert groups.split(t, 1) is None                                              # one builder allowed
    assert groups.split(t + "- [ ] c\n", 3) is None                                # a task without files: nothing is guessed
    assert groups.split("- [ ] a [files: a.py]\n- [ ] b [files: a.py]\n", 3) is None   # everything shares a file
    assert len(groups.split("- [ ] a [files: a]\n- [ ] b [files: b]\n- [ ] c [files: c]\n", 2)) == 2  # folded into the limit


def _git(project, *a):
    return subprocess.run(["git", *a], cwd=project, capture_output=True, text=True).stdout.strip()


def test_two_builders_work_on_one_card(project, mine, log, monkeypatch):  # noqa: F811
    cfg, calls = mine
    cfg["builders"] = 2
    monkeypatch.setenv("FAKEAI_FILES", "a.py|b.py")
    add_card(project)
    assert Pipeline(project, cfg, log, Runner(project, cfg, log)).run() == 0
    assert [c.id for c in Board(project).cards("done")] == ["001-thing"]
    assert (project / "a.py").exists() and (project / "b.py").exists()               # both parts merged into main
    parts = [json.loads(f.read_text(encoding="utf-8")) for f in calls.parent.glob("part-*.json")]
    assert len(parts) == 2 and all(str(project) not in r["cwd"] for r in parts)      # each part ran in its own folder
    assert _git(project, "branch", "--list", "part/*") == "" and _git(project, "worktree", "list").count("\n") == 0


def test_a_part_that_touches_other_files_falls_back_to_one_builder(project, mine, log, monkeypatch):  # noqa: F811
    cfg, _ = mine
    cfg["builders"] = 2
    monkeypatch.setenv("FAKEAI_FILES", "a.py|b.py")
    monkeypatch.setenv("FAKEAI_ROGUE", "1")
    add_card(project)
    assert Pipeline(project, cfg, log, Runner(project, cfg, log)).run() == 0
    assert not (project / "evil.py").exists()                                        # the rogue parts were dropped
    assert (project / "001-thing.py").exists()                                       # one builder did the card instead
    assert _git(project, "branch", "--list", "part/*") == ""
