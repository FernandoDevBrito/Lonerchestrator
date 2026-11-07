import json

import pytest
from conftest import CARD, add_card

from orch import tui

SCREENS = range(5)


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
    board, flow, planner, agents = ("\n".join(lines(project, s)) for s in range(4))
    assert "To do" in board and "Add thing" in board and "Needs you" in board and "001" in board
    assert "REVIEW" in flow and "qa ✓" in flow and "SPLIT" in flow and "BUILD" in flow and "Activity" in flow
    assert "Goal" in planner and "Criteria" in planner and "○ thing() returns 1" in planner
    assert "builder" in agents and "RESULT: DONE" in agents
    assert "reviewing · qa ✓  cross" in flow


def test_planner_checklist_keeps_wrapped_text():
    out = tui.checklist("- [ ] " + "word " * 40 + "\n- [x] done task", 40)
    assert out[0].startswith("○ word") and out[1].startswith("  word") and any("✓ done task" in ln for ln in out)
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


def seed_ais(project):
    from orch import intro
    intro.save_ais(project, {"claude": {"installed": True, "logged_in": True, "models": ["sonnet", "opus", "haiku"]},
                             "agy": {"installed": True, "logged_in": True, "models": ["gemini-4-argon-high", "gemini-3.8-flash-low"]}})


def test_ais_tab_shows_checklist_roles_and_live_usage(project):
    import time

    from orch import usage
    seed_ais(project)
    usage.set_claude_limits({"status": "allowed", "unifiedWindows": {
        "five_hour": {"utilization": 0.52, "resetsAt": time.time() + 8130, "status": "allowed"},
        "seven_day": {"utilization": 0.19, "resetsAt": time.time() + 260000, "status": "allowed"}}})
    run = project / ".orchestrator" / "runs" / "r1"
    run.mkdir(parents=True)
    (project / ".orchestrator" / "state.json").write_text(json.dumps({"run": "r1", "card": None, "phase": "idle"}))
    u = usage.Usage(run)
    u.add("claude", "sonnet", "builder", 120_000, 3_100)
    u.add("agy", "gemini-4-argon-high", "cross", 18_000, 40)
    out = "\n".join(lines(project, 4))
    assert "◉ sonnet" in out and "○ gemini-4-argon-high" in out and "Who does what" in out and "Use these AIs" in out
    assert "52%" in out and "19%" in out and "resets in 2h 15m" in out and "not shown by agy" in out
    assert "123.1k" in out and "18.0k" in out
    head = out.split("\n")[0]
    assert "● claude 5h 52% wk 19%" in head and "● agy 18.0k tok" in head


def test_ais_tab_without_data_does_not_crash(project):
    out = "\n".join(lines(project, 4))
    assert "not detected" in out and "no data yet" in out


def test_ais_tab_keys_toggle_cycle_and_refresh(project, monkeypatch):
    from orch import config, menu, usage
    seed_ais(project)
    called = []
    monkeypatch.setattr(usage, "probe_in_background", lambda p: called.append(p))
    ui = tui.UI()
    ui.screen = 4

    def key(k):
        tui.handle(k, ui, tui.Ctx(project, ui), None)

    key("down")                                   # sonnet -> opus
    key("down")                                   # -> haiku
    key(" ")
    assert "claude/haiku" not in menu.enabled(project) and "unchecked" in ui.msg
    key("down")                                   # first agy model
    key("\r")
    assert "agy/gemini-4-argon-high" in menu.enabled(project)
    ui.cursor = len(menu.available(project)) + menu.SLOTS.index("cross")            # the 'cross' role row
    key("right")
    assert "cross ->" in ui.msg and menu.assigned(config.load(project), "cross") in menu.enabled(project)
    key("u")
    assert called == [project] and "limits" in ui.msg
    key("5")
    assert ui.screen == 4
    assert len(lines(project, 4, ui=ui)) == tui.H
