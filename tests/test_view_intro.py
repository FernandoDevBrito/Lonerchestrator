import json

from conftest import add_card

from orch import intro, view

AIS = {"claude": {"installed": True, "logged_in": True, "models": ["sonnet", "opus", "haiku"]},
       "agy": {"installed": True, "logged_in": True, "models": ["gemini-4-argon-high", "gemini-3.8-flash-high"]}}


def test_parse_agy_models():
    out = "Fetching available models...\ngemini-4-argon-high\tGemini 4 Argon (High)\nclaude-opus-5-5-low\tClaude Opus\n"
    assert intro.parse_agy_models(out) == ["gemini-4-argon-high", "claude-opus-5-5-low"]


def test_intro_assume_yes_writes_roles_and_prints_board(project, capsys):
    raw = intro.run_intro(project, assume_yes=True, ais=AIS)
    assert raw["roles"]["builder"] == {"cli": "claude", "model": "sonnet"}
    assert [r["name"] for r in raw["reviewers"]] == ["qa", "cross"]
    assert raw["reviewers"][1]["kind"] == "agy"                       # cross-review uses a different model family
    assert intro.configured(project)
    assert json.loads((project / ".orchestrator" / "ais.json").read_text())["ais"]["agy"]["logged_in"]
    assert "REVIEW" in capsys.readouterr().out


def test_intro_interactive_picks(project):
    answers = iter(["2", "", "", "1", "3"])        # planner=opus, builder/retro default, qa=claude/sonnet, cross=claude/haiku
    raw = intro.run_intro(project, ask=lambda _: next(answers), out=lambda *_: None, ais=AIS)
    assert raw["roles"]["planner"]["model"] == "opus"
    assert raw["reviewers"][1] == {"name": "cross", "kind": "claude", "model": "haiku", "required": True, "agent": "qa"}


def test_intro_requires_claude(project):
    off = {**AIS, "claude": {"installed": True, "logged_in": False, "models": []}}
    assert intro.run_intro(project, assume_yes=True, ais=off, out=lambda *_: None) is None


def test_render_idle_and_running(project):
    add_card(project)
    idle = view.render(project, 115, 36, color=False)
    for word in ("CARD", "PLAN", "BUILD", "GUARD", "CI", "REVIEW", "MERGE", "BACKLOG (1)", "001-thing"):
        assert word in idle
    root = project / ".orchestrator"
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    (root / "state.json").write_text(json.dumps({"run": "r1", "card": "001-thing", "phase": "review 2"}))
    ev = [{"ts": "2026-01-01 10:00:00", "kind": "build", "card": "001-thing", "agent": "backend", "result": "attempt 2: done"},
          {"ts": "2026-01-01 10:00:09", "kind": "review", "card": "001-thing", "agent": "qa", "result": "APPROVED"}]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev))
    live = view.render(project, 115, 36, color=False)
    assert "RUNNING" in live and "attempt: 2/3" in live and "qa OK" in live
    assert "MERGE" in live
    # narrow terminals still render
    assert "REVIEW" in view.render(project, 90, 30, color=False)


def test_stage_status_resets_later_stages_on_retry():
    evs = [{"kind": k, "result": r} for k, r in (("plan", "planned"), ("build", "done"), ("ci", "FAIL"), ("build", "done"))]
    st = view.stage_status(evs, cur=view.PHASE_IDX["guardrails"])
    assert st[:3] == ["ok", "ok", "ok"] and st[3] == "running" and st[4:] == ["pending"] * 3
