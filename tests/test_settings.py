import json

from conftest import add_card, home, sh

from orch import checks, config, intro, settings, trust, tui

AIS_OK = {"claude": {"installed": True, "logged_in": True, "models": ["sonnet", "opus"]},
          "agy": {"installed": True, "logged_in": True, "models": ["gemini-x"]}}


def status(project, title_part, **kw):
    return next(s for s, t, _ in checks.readiness(project, **kw) if title_part in t)


def hint(project, title_part, **kw):
    return next(h for _, t, h in checks.readiness(project, **kw) if title_part in t)


# ---- settings ------------------------------------------------------------------------------------------------
def test_bool_toggle_persists_and_leaves_other_keys_alone(project):
    assert settings.value(project, "split") is True
    assert settings.change(project, "split") == "Split big cards: off"
    assert settings.value(project, "split") is False
    assert config.read_raw(project) == {"split": False}                                              # only what changed is stored
    assert settings.change(project, "git_hooks") == "Run my git hooks: on"


def test_choice_cycles_wraps_and_handles_unknown_values(project):
    seen = []
    for _ in range(5):
        settings.change(project, "max_attempts", 1)
        seen.append(settings.value(project, "max_attempts"))
    assert seen == [4, 5, 1, 2, 3]                                       # default 3, wraps 5 -> 1
    settings.change(project, "max_attempts", -1)
    assert settings.value(project, "max_attempts") == 2
    raw = config.read_raw(project)
    raw["max_attempts"] = 7                                              # hand-edited, not in the list
    config.write_raw(project, raw)
    settings.change(project, "max_attempts", 1)
    assert settings.value(project, "max_attempts") == 1
    assert settings.change(project, "card_timeout_min") == "Time limit per card: 90 min"


def test_nested_setting_keeps_sibling_guardrails(project):
    settings.change(project, "guardrails.max_files", 1)
    cfg = config.load(project)
    assert cfg["guardrails"]["max_files"] == 50
    assert cfg["guardrails"]["max_diff_lines"] == 1000 and cfg["guardrails"]["scan_secrets"] is True


def test_branch_choice_skips_card_branches(project):
    sh(project, "git", "branch", "scratch")
    sh(project, "git", "branch", "card/001-x")
    assert settings.branches(project) == ["main", "scratch"]
    assert settings.change(project, "base") == "Base branch: scratch"
    assert settings.change(project, "base") == "Base branch: main"
    assert settings.change(project, "base", -1) == "Base branch: scratch"


def test_ci_text_is_validated_cleaned_and_approved(project):
    assert "press Enter" in settings.change(project, "ci")
    assert "1 to 300" in settings.set_text(project, "ci", "   ")
    assert "1 to 300" in settings.set_text(project, "ci", "x" * 301)
    assert settings.set_text(project, "ci", "npm test\x1b[2J  &&  npm run lint\n") == "CI command saved and approved"
    cfg = config.load(project)
    assert cfg["ci"] == "npm test[2J && npm run lint"                    # control characters dropped, whitespace collapsed
    assert trust.is_trusted(project, cfg)


# ---- readiness checks ------------------------------------------------------------------------------------------
def test_git_checks(project, tmp_path):
    assert status(project, "Git:") == "ok"
    (project / "dirty.txt").write_text("x")
    assert status(project, "uncommitted changes") == "ok" and "yours stay as they are" in hint(project, "uncommitted changes")   # the run works around them
    sh(project, "git", "checkout", "-q", "-b", "side")
    assert status(project, "Uncommitted changes on 'side'") == "warn" and "switch to 'main'" in hint(project, "Uncommitted")
    sh(project, "git", "checkout", "-q", "main")
    config.write_raw(project, {"base": "nope"})
    assert status(project, "Base branch") == "fail" and "Settings" in hint(project, "Base branch")
    outside = tmp_path / "plain"
    outside.mkdir()
    assert status(outside, "Git repository") == "fail" and "git init" in hint(outside, "Git repository")


def test_claude_states_come_from_the_detected_ais(project):
    assert status(project, "Claude Code") == "warn" and "press d" in hint(project, "Claude Code")
    intro.save_ais(project, {"claude": {"installed": False, "logged_in": False, "models": []}})
    assert status(project, "Claude Code") == "fail" and "claude.com" in hint(project, "Claude Code")
    intro.save_ais(project, {"claude": {"installed": True, "logged_in": False, "models": []}})
    assert "log in" in hint(project, "Claude Code") and status(project, "Claude Code") == "fail"
    intro.save_ais(project, AIS_OK)
    assert status(project, "Claude Code") == "ok"


def test_reviewer_checks(project):
    intro.save_ais(project, AIS_OK)
    raw = {"reviewers": [{"name": "qa", "kind": "claude", "agent": "qa", "model": "sonnet"}, {"name": "cross", "kind": "agy", "model": "gemini-x"}]}
    config.write_raw(project, raw)
    assert status(project, "reviewers") == "ok"
    raw["reviewers"][1] = {"name": "cross", "kind": "claude", "agent": "qa", "model": "sonnet"}
    config.write_raw(project, raw)
    assert status(project, "same model") == "warn"
    raw["reviewers"][1] = {"name": "cross", "kind": "agy", "model": "gemini-x"}
    config.write_raw(project, raw)
    intro.save_ais(project, {**AIS_OK, "agy": {"installed": False, "logged_in": False, "models": []}})
    assert status(project, "Antigravity") == "fail" and "agy" in hint(project, "Antigravity")


def test_ci_checks_missing_script_untrusted_then_trusted(project):
    assert status(project, "missing") == "fail"                          # default: the folder's ci.sh, not written yet
    (home(project) / "ci.sh").write_text("exit 0\n")
    assert status(project, "not approved") == "warn"
    trust.trust(project, config.load(project))
    assert status(project, "CI command approved") == "ok"


def test_context_check_tells_placeholder_from_filled(project):
    (home(project) / "context").mkdir()
    ctx = home(project) / "context" / "project.md"
    ctx.write_text("# Project context\n\n<!-- Fill me -->\n- Stack:\n- Conventions:\n")
    assert status(project, "context/project.md") == "warn"
    ctx.write_text("# Project context\n\n- Stack: Python 3.10, pytest and ruff\n- Conventions: flat modules\n")
    assert status(project, "Project context") == "ok"


def test_claude_folder_trust_is_read_without_trusting_parents(project, tmp_path):
    cj = tmp_path / "claude.json"
    assert not [t for _, t, _ in checks.readiness(project, claude_json=cj) if "Claude Code" in t and "Folder" in t]   # unreadable: no opinion
    key = str(project).replace("\\", "/")
    cj.write_text(json.dumps({"projects": {str(project.parent).replace("\\", "/"): {"hasTrustDialogAccepted": True}}}))
    assert status(project, "Folder not trusted", claude_json=cj) == "warn"                                          # parent does not count
    cj.write_text(json.dumps({"projects": {key: {"hasTrustDialogAccepted": True}}}))
    assert status(project, "Folder trusted", claude_json=cj) == "ok"


def test_backlog_check_and_summary(project):
    assert status(project, "No cards") == "warn"
    add_card(project)
    assert status(project, "card(s)") == "ok"
    ready, text = checks.summary([("ok", "a", ""), ("warn", "b", "")])
    assert ready is True and text == "1 to review"
    assert checks.summary([("fail", "a", "")]) == (False, "1 to fix, 0 to review")
    assert checks.summary([("ok", "a", "")]) == (True, "ready to run")


# ---- the panel ---------------------------------------------------------------------------------------------------
def test_settings_tab_renders_settings_and_readiness(project):
    out = "\n".join(tui.render(project, 5, color=False).split("\n"))
    for word in ("Settings", "Base branch", "CI command", "Attempts per card", "Ready to run?", "About this setting"):
        assert word in out
    assert {tui.vlen(ln) for ln in out.split("\n")} == {tui.W}


def test_settings_tab_keys_change_persist_and_edit_text(project):
    ui = tui.UI()
    ui.screen = 5

    def key(k):
        tui.handle(k, ui, tui.Ctx(project, ui), None)

    key("down")
    key("down")                                                          # Attempts per card
    key("right")
    assert settings.value(project, "max_attempts") == 4 and "Attempts per card: 4" in ui.msg
    key("down")                                                          # Cards at the same time
    key("right")
    assert settings.value(project, "parallel") == 2
    key("down")                                                          # Builders per card
    key("right")
    assert settings.value(project, "builders") == 2
    key("down")                                                          # Split big cards
    key(" ")
    assert settings.value(project, "split") is False
    ui.scur = 1                                                          # CI command
    key("\r")
    assert ui.mode == "edit" and ui.buf == 'bash "{folder}/ci.sh"'
    out = tui.render(project, 5, ui=ui, color=False)
    assert "Editing CI command" in out and "type the new value" in out and {tui.vlen(ln) for ln in out.split("\n")} == {tui.W}
    for _ in range(len(ui.buf)):
        key("\x7f")
    for ch in "pytest -q":                                               # 'q' is text here, it must not quit
        key(ch)
    key("\r")
    assert ui.mode is None and config.load(project)["ci"] == "pytest -q" and "approved" in ui.msg
    assert trust.is_trusted(project, config.load(project))
    ui.scur = 1
    key("\r")
    key("x")
    key("\x1b")
    assert ui.mode is None and config.load(project)["ci"] == "pytest -q" and "cancelled" in ui.msg
    key("5")
    assert ui.screen == 4


def test_ais_tab_tells_how_to_fix_an_ai_that_is_not_ready(project):
    intro.save_ais(project, {"claude": {"installed": True, "logged_in": False, "models": []},
                             "agy": {"installed": False, "logged_in": False, "models": []}})
    out = "\n".join(tui.render(project, 4, color=False).split("\n"))
    assert "run `claude`, log in, then press d" in out and "antigravity.google" in out
    assert "…" not in "".join(out.split("\n")[5:8])               # the hints fit their column, nothing is cut off
    assert {tui.vlen(ln) for ln in out.split("\n")} == {tui.W}
