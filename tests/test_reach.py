"""Any AI, any model, any effort, any area: effort reaches each CLI the way it takes one, areas come from the config, the docs agent ships."""
from orch import board, checks, config, intake, menu, providers
from orch.cli import TEMPLATES


def test_effort_reaches_each_cli_in_its_own_words():
    reg = providers.registry()
    assert providers.effort_for(reg["claude"], "xhigh") == "xhigh"                         # native: --effort
    assert providers.effort_for(reg["codex"], "max") == "high"                             # above its scale: lowered to its highest
    argv, _ = providers.build_argv(reg["codex"], "default", "hi", "read", "medium")
    assert argv[argv.index("-c") + 1] == "model_reasoning_effort=medium"
    assert providers.effort_for(reg["gemini"], "high") is None                             # no way to pass it: ignored, never a broken command
    assert "-c" not in providers.build_argv(reg["gemini"], "default", "hi", "read", "high")[0]
    assert providers.effort_for(reg["claude"], None) is None


def test_claude_runner_passes_effort_only_when_set(tmp_path, monkeypatch):
    from orch import agents
    seen = []
    r = agents.Runner(tmp_path, config.load(tmp_path), log=None)
    monkeypatch.setattr(r, "_run", lambda role, cmd, claude: seen.append(cmd))
    r.claude("builder", "backend", "go", model="opus", effort="high")
    r.claude("builder", "backend", "go")
    assert seen[0][seen[0].index("--effort") + 1] == "high" and "--effort" not in seen[1]


def test_effort_survives_a_model_change(tmp_path):
    cfg = config.load(tmp_path)
    raw = {}
    menu._assign(raw, cfg, "builder", "claude/opus", "xhigh")
    config.write_raw(tmp_path, raw)
    cfg = config.load(tmp_path)
    menu._assign(raw, cfg, "builder", "claude/sonnet")
    assert raw["roles"]["builder"] == {"cli": "claude", "model": "sonnet", "effort": "xhigh"}
    menu._assign(raw, cfg, "qa", "claude/opus", "max")
    assert next(r for r in raw["reviewers"] if r["name"] == "qa")["effort"] == "max"


def test_areas_come_from_the_config(tmp_path):
    cfg = config.load(tmp_path)
    assert "docs" in config.areas(cfg)
    config.write_raw(tmp_path, {"agents": {"data": "data-eng"}})
    cfg = config.load(tmp_path)
    assert "data" in config.areas(cfg)
    board.Board(tmp_path).ensure()
    path = board.create_card(tmp_path, "Load the sales feed", "data", goal="Load it nightly.", criteria=["the feed loads"])
    card = board.Card(path)
    assert card.problems(config.areas(cfg)) == [] and card.problems(("backend",))


def test_docs_and_research_requests_go_to_the_docs_agent(tmp_path):
    assert intake.guess_area("Write a getting started guide") == "docs"
    assert intake.guess_area("Research which charting library fits us") == "docs"
    assert intake.guess_area("Add an API endpoint to compare prices") == "backend"   # code words win
    assert intake.parse('{"title": "t", "area": "docs", "goal": "g", "criteria": ["c"]}')["area"] == "docs"
    assert '"docs"' in intake.prompt("x")


def test_the_docs_agent_ships_and_readiness_names_a_missing_one(tmp_path):
    text = (TEMPLATES / "dot-claude" / "agents" / "docs.md").read_text(encoding="utf-8")
    for must in ("name: docs", "PHASE=PLAN", "PHASE=IMPLEMENT", "RESULT: PLANNED", "RESULT: DONE", "RESULT: BLOCKED", "context/decisions.md", "path/to/file.py:42"):
        assert must in text, must
    assert (TEMPLATES / "memory" / "docs.md").is_file()
    got = checks.check_agents(checks.Env(tmp_path))
    assert got[0][0] == "warn" and "docs" in got[0][1]
