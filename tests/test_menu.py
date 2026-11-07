import json

from orch import config, intro, menu

AIS = {"claude": {"installed": True, "logged_in": True, "models": ["sonnet", "opus", "haiku"]},
       "agy": {"installed": True, "logged_in": True, "models": ["gemini-4-argon-high", "gemini-3.8-flash-low"]}}


def setup(project, ais=AIS):
    intro.save_ais(project, ais)


def test_available_and_default_enabled(project):
    assert menu.available(project) == []                       # nothing detected yet
    setup(project)
    assert menu.available(project)[0] == ("claude", "sonnet") and ("agy", "gemini-4-argon-high") in menu.available(project)
    assert menu.enabled(project) == ["claude/sonnet", "claude/opus", "claude/haiku"]     # default: all Claude, agy is opt-in


def test_toggle_on_and_off_persists(project):
    setup(project)
    assert "checked" in menu.toggle(project, "agy/gemini-4-argon-high")
    assert "agy/gemini-4-argon-high" in menu.enabled(project)
    assert json.loads((project / ".orchestrator" / "config.json").read_text())["use"][-1] == "agy/gemini-4-argon-high"
    assert "unchecked" in menu.toggle(project, "claude/haiku")
    assert "claude/haiku" not in menu.enabled(project)


def test_unchecking_a_model_in_use_reassigns_the_slot(project):
    setup(project)
    menu.toggle(project, "agy/gemini-4-argon-high")
    raw = config.read_raw(project)
    raw["reviewers"] = [{"name": "qa", "kind": "claude", "agent": "qa", "model": "sonnet"},
                        {"name": "cross", "kind": "agy", "model": "gemini-4-argon-high"}]
    raw["roles"] = {"splitter": {"cli": "claude", "model": "haiku"}}
    config.write_raw(project, raw)
    menu.toggle(project, "agy/gemini-4-argon-high")            # uncheck what cross uses
    assert menu.assigned(config.load(project), "cross") in menu.enabled(project)
    menu.toggle(project, "claude/haiku")                       # splitter used haiku
    assert menu.assigned(config.load(project), "splitter") in ("claude/sonnet", "claude/opus")
    assert menu.problems(config.load(project)) == []


def test_cannot_uncheck_the_last_editing_ai(project):
    setup(project)
    menu.toggle(project, "claude/opus")
    menu.toggle(project, "claude/haiku")
    msg = menu.toggle(project, "claude/sonnet")
    assert "at least one AI that can edit" in msg and "claude/sonnet" in menu.enabled(project)


def test_cycle_roles_only_among_enabled_and_editing_ais_for_workers(project):
    setup(project)
    raw = config.read_raw(project)
    raw["providers"] = {"agy": {"can_edit": False}}                                  # a text-only AI can review but not build
    config.write_raw(project, raw)
    menu.toggle(project, "agy/gemini-3.8-flash-low")
    seen = {menu.assigned(config.load(project), "planner")}
    for _ in range(4):
        menu.cycle(project, "planner", 1)
        seen.add(menu.assigned(config.load(project), "planner"))
    assert seen <= {"claude/sonnet", "claude/opus", "claude/haiku"}                 # planner never lands on agy
    kinds = set()
    for _ in range(5):
        menu.cycle(project, "cross", 1)
        kinds.add(menu.assigned(config.load(project), "cross").split("/")[0])
    assert kinds == {"claude", "agy"}                                                # reviewers can use any enabled AI
    assert menu.options(project, "cross") == menu.enabled(project)


def test_cycle_with_nothing_enabled_for_slot(project):
    assert "No model enabled" in menu.cycle(project, "planner", 1)                  # no AI detected


def test_problems_flags_unchecked_models_only_after_menu_use(project):
    setup(project)
    assert menu.problems(config.load(project)) == []                                # never used the menu: no opinion
    raw = config.read_raw(project)
    raw["use"] = ["claude/opus"]
    config.write_raw(project, raw)
    bad = menu.problems(config.load(project))
    assert any("planner" in b for b in bad) and all("not checked" in b for b in bad)


def test_any_detected_ai_is_listed_and_can_fill_a_role(project):
    ais = {**AIS, "codex": {"installed": True, "logged_in": True, "models": ["default"]}}
    setup(project, ais)
    assert ("codex", "default") in menu.available(project)
    menu.toggle(project, "codex/default")
    assert "codex/default" in menu.options(project, "builder") and "codex/default" in menu.options(project, "suggester")
    while menu.cycle(project, "builder", 1) and menu.assigned(config.load(project), "builder") != "codex/default":
        pass
    assert config.load(project)["roles"]["builder"] == {"cli": "codex", "model": "default"}
