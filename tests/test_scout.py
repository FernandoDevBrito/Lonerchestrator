"""Studying the repository to fill context/project.md: facts without an AI, an AI draft when it answers, never overwriting what the user wrote."""
import json
import subprocess
import time
from argparse import Namespace

import pytest
from conftest import home, sh
from test_web import server  # noqa: F401  (the local web server fixture)

from orch import checks, cli, config, scout


@pytest.fixture
def repo(project):
    (project / "package.json").write_text(json.dumps({"name": "shop", "description": "A tiny shop", "scripts": {"test": "jest", "lint": "eslint .", "build": "vite build"},
                                                       "dependencies": {"react": "18"}}), encoding="utf-8")
    (project / "pyproject.toml").write_text('[project]\nname = "shop-api"\n[tool.pytest.ini_options]\n[tool.ruff]\n', encoding="utf-8")
    (project / "README.md").write_text("# Shop\n\nA small web shop with a React front end and a Python API.\n", encoding="utf-8")
    (project / "src").mkdir()
    (project / "src" / "app.tsx").write_text("export {}\n", encoding="utf-8")
    (project / "api.py").write_text("x = 1\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_api.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (project / ".env").write_text("API_KEY=sk-live-should-never-be-read\n", encoding="utf-8")
    sh(project, "git", "add", "-A", "-f")
    sh(project, "git", "commit", "-qm", "add shop")
    return project


GOOD = ("```markdown\n# Project context\n- What it is: A small web shop (React + Python API).\n- Stack: TypeScript/React, Python.\n"
        "- How to run / test / lint / build (one command each): npm test; npm run lint; npm run build; python -m pytest.\n"
        "- Conventions (naming, structure, style): src/ for the front end, tests/ for Python tests.\n"
        "- Things agents must never do here: edit .claude/, CLAUDE.md, deploy, commit secrets.\n```")


def test_facts_come_from_the_repository_and_never_from_secrets(repo):
    f = scout.gather(repo)
    text = scout.facts_text(f)
    assert "TypeScript (React)" in text and "Python" in text and "npm test" in text and "npm run lint" in text and "python -m pytest" in text
    assert "A small web shop" in text and "tests" in f["tests"] and "react" in text
    assert "sk-live" not in text and ".env" not in text                                          # secrets are never read nor listed


def test_without_an_ai_the_facts_are_written_as_they_are(repo):
    assert not scout.filled(repo)
    content, source = scout.study(repo, use_ai=False)
    assert source == "basic" and "npm test" in content and "Stack:" in content and "never do here" in content
    (home(repo) / "context").mkdir(exist_ok=True)
    (home(repo) / "context" / "project.md").write_text(content, encoding="utf-8")
    assert scout.filled(repo) and not [c for c in checks.readiness(repo) if "project.md is empty" in c[1]]


def test_an_ai_draft_is_used_only_when_it_has_the_five_bullets(repo):
    assert scout.parse(GOOD).startswith("# Project context") and "npm test" in scout.parse(GOOD) and scout.MARK in scout.parse(GOOD)
    for bad in (None, "", "Sure! Here is the file.", "# Project context\n- What it is: x\n- Stack: y\n"):
        assert scout.parse(bad) is None
    assert scout.study(repo, ask=lambda p: GOOD)[1] == "ai"
    assert scout.study(repo, ask=lambda p: "nope")[1] == "basic"                                   # a useless reply falls back to the facts
    assert scout.study(repo, ask=lambda p: 1 / 0)[1] == "basic"                                    # an unreachable AI never stops anything
    assert "<<<FACTS" in scout.prompt(scout.gather(repo))                                          # the facts are fenced as data


def test_ensure_writes_into_the_folder_and_never_overwrites(repo):
    say = []
    assert scout.ensure(repo, ask=lambda p: GOOD, say=say.append) == "ai"
    f = home(repo) / "context" / "project.md"
    assert "React" in f.read_text(encoding="utf-8") and "add shop" in subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout.strip() == ""      # no file, no commit in the project
    f.write_text(f.read_text(encoding="utf-8") + "- My own rule: always use tabs\n", encoding="utf-8")
    assert scout.ensure(repo, ask=lambda p: GOOD, say=say.append) is None                           # filled: left alone
    assert "always use tabs" in f.read_text(encoding="utf-8")
    assert scout.ensure(repo, ask=lambda p: GOOD, force=True, say=say.append) == "ai" and "always use tabs" not in f.read_text(encoding="utf-8")


def test_context_command(repo, capsys):
    assert cli.cmd_context(Namespace(force=False, basic=True), repo) == 1 and "lonerchestrator init" in capsys.readouterr().out
    config.write_raw(repo, {"base": "main"})                                                       # what `init` writes
    assert cli.cmd_context(Namespace(force=False, basic=True), repo) == 0
    assert scout.filled(repo)
    capsys.readouterr()
    assert cli.cmd_context(Namespace(force=False, basic=True), repo) == 0
    assert "never overwritten" in capsys.readouterr().out


def test_the_web_button_fills_it_in_the_background(server, repo):  # noqa: F811
    call, *_ = server
    st = json.loads(call("GET", "/api/settings")[1])
    assert any(c["action"] == "context" for c in st["checks"])
    assert call("POST", "/api/context", {})[0] == 200
    for _ in range(50):
        if scout.filled(repo):
            break
        time.sleep(0.1)
    assert scout.filled(repo)
    assert not any(c["action"] == "context" for c in json.loads(call("GET", "/api/settings")[1])["checks"])
    assert "never overwritten" in json.loads(call("POST", "/api/context", {})[1])["msg"]
