import json

from orch import folder, intro, view

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
    assert json.loads((folder.of(project) / "ais.json").read_text())["ais"]["agy"]["logged_in"]
    assert "REVIEW" in capsys.readouterr().out


def test_intro_interactive_picks(project):
    answers = iter(["", "2", "", "", "1", "3"])    # splitter default, planner=opus, builder/retro default, qa=claude/sonnet, cross=claude/haiku
    raw = intro.run_intro(project, ask=lambda _: next(answers), out=lambda *_: None, ais=AIS)
    assert raw["roles"]["planner"]["model"] == "opus"
    assert raw["reviewers"][1] == {"name": "cross", "kind": "claude", "model": "haiku", "required": True, "agent": "qa"}


def test_intro_needs_one_ai_that_can_edit(project):
    off = {name: {"installed": True, "logged_in": False, "models": []} for name in AIS}
    assert intro.run_intro(project, assume_yes=True, ais=off, out=lambda *_: None) is None
    only_agy = {**off, "agy": AIS["agy"]}                       # Claude is optional now: any AI that can edit files will do
    raw = intro.run_intro(project, assume_yes=True, ais=only_agy, out=lambda *_: None)
    assert raw["roles"]["builder"]["cli"] == "agy"


def test_stage_status_resets_later_stages_on_retry():
    evs = [{"kind": k, "result": r} for k, r in (("plan", "planned"), ("build", "done"), ("ci", "FAIL"), ("build", "done"))]
    st = view.stage_status(evs, cur=view.PHASE_IDX["guardrails"])
    assert st[:3] == ["ok", "ok", "ok"] and st[3] == "running" and st[4:] == ["pending"] * 2
