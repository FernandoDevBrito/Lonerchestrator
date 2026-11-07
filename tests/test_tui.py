import json

import pytest
from conftest import CARD, add_card

from orch import tui

SCREENS = range(4)


def seed_running(project):
    root = project / ".orchestrator"
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    (root / "state.json").write_text(json.dumps({"run": "r1", "card": "001-thing", "phase": "review 2"}))
    ev = [{"ts": "2026-01-01 10:00:00", "kind": "build", "card": "001-thing", "agent": "backend", "result": "attempt 2: done"},
          {"ts": "2026-01-01 10:00:09", "kind": "review", "card": "001-thing", "agent": "qa", "result": "APPROVED"}]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev))
    (root / "streams").mkdir(exist_ok=True)
    (root / "streams" / "builder.log").write_text("> Edit x.py\n" + "a very long line " * 20 + "\nRESULT: DONE\n")


def lines(project, screen, **kw):
    return tui.render(project, screen, color=False, **kw).split("\n")


@pytest.mark.parametrize("state", ["empty", "idle_cards", "running"])
def test_every_screen_is_exactly_standard_size(project, state):
    if state != "empty":
        add_card(project, "001-thing")
        add_card(project, "002-other", CARD.replace("Add thing", "A very long title " * 6))
    if state == "running":
        seed_running(project)
    for s in SCREENS:
        out = lines(project, s)
        assert len(out) == tui.H, (s, len(out))
        assert {tui.vlen(ln) for ln in out} == {tui.W}, (s, [(i, tui.vlen(ln)) for i, ln in enumerate(out) if tui.vlen(ln) != tui.W][:3])


def test_screens_show_their_content(project):
    add_card(project)
    seed_running(project)
    board, flow, planner, agents = ("\n".join(lines(project, s)) for s in SCREENS)
    assert "TO DO" in board and "Add thing" in board and "NEEDS YOU" in board
    assert "REVIEW" in flow and "qa OK" in flow and "RUNNING" in flow and "SPLIT" in flow
    assert "GOAL" in planner and "ACCEPTANCE CRITERIA" in planner and "[ ] thing() returns 1" in planner
    assert "builder" in agents and "RESULT: DONE" in agents
    assert "reviewing: qa OK, cross thinking" in flow


def test_planner_checklist_keeps_wrapped_text():
    out = tui.checklist("- [ ] " + "word " * 40 + "\n- [x] done task", 40)
    assert out[0].startswith("[ ] word") and out[1].startswith("    word") and any("[x] done task" in ln for ln in out)
    assert all("word" in ln for ln in out[:-1])


def test_keys_move_selection_and_switch_views(project):
    add_card(project, "001-thing")
    add_card(project, "002-two")
    ui = tui.UI()
    x = tui.Ctx(project, ui)

    class R:
        started = stopped = 0
        start = lambda self: setattr(self, "started", 1)  # noqa: E731
        stop = lambda self: setattr(self, "stopped", 1)  # noqa: E731

    r = R()
    tui.handle("down", ui, x, r)
    assert ui.row == 1
    tui.handle("right", ui, x, r)
    assert ui.col == 1
    tui.handle("3", ui, x, r)
    assert ui.screen == 2
    tui.handle("\t", ui, x, r)
    assert ui.screen == 3
    tui.handle("r", ui, x, r)
    tui.handle("x", ui, x, r)
    assert (r.started, r.stopped) == (1, 1)


def test_selection_clamps_when_column_is_shorter(project):
    add_card(project)
    ui = tui.UI()
    ui.col, ui.row = 3, 9
    x = tui.Ctx(project, ui)
    assert (ui.col, ui.row) == (3, 0) and x.selected is None
    assert len(lines(project, 0, ui=ui)) == tui.H
