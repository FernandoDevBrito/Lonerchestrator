"""Any AI CLI the user describes in config can fill every role: proved with a fake third-party CLI through the real Runner + Pipeline."""
import json
import sys
from pathlib import Path

import pytest
from conftest import add_card, home

from orch import providers
from orch.agents import Runner
from orch.pipeline import Pipeline

FAKE = str(Path(__file__).with_name("fakeai.py"))


@pytest.fixture
def mine(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKEAI_LOG", str(tmp_path / "calls.jsonl"))
    cfg["providers"] = {"mine": {"name": "My AI", "cmd": [sys.executable, FAKE], "prompt_via": "stdin", "model_args": ["--m", "{model}"],
                                 "edit_args": ["--rw"], "read_args": ["--ro"], "models": ["big"]}}
    cfg["roles"] = {r: {"cli": "mine", "model": "big"} for r in ("splitter", "planner", "builder", "retro", "suggester")}
    cfg["reviewers"] = [{"name": "qa", "kind": "mine", "agent": "qa", "model": "big"}, {"name": "cross", "kind": "mine", "agent": "qa"}]
    return cfg, tmp_path / "calls.jsonl"


def records(calls):
    """Every note the fake AI wrote (one file each), oldest first."""
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(calls.parent.glob("calls-*.json"))]


def test_custom_ai_runs_every_role(project, mine, log):
    cfg, calls = mine
    add_card(project)
    assert Pipeline(project, cfg, log, Runner(project, cfg, log)).run() == 0
    assert (project / "001-thing.py").exists()
    assert [p.name for p in (home(project) / "board" / "done").glob("*.md")] == ["001-thing.md"]
    argv = [r["argv"] for r in records(calls) if "argv" in r]
    edit = [a for a in argv if "--rw" in a]
    read = [a for a in argv if "--ro" in a]
    assert len(edit) >= 3 and len(read) >= 2                                      # planner+builder+retro edit, two reviewers only read
    assert not any("--rw" in a and "--ro" in a for a in argv)
    assert ["--m", "big", "--ro"] in read and ["--ro"] in read                    # no model set -> no model flag


def test_unknown_or_text_only_ai_is_refused_early(project, mine, log):
    cfg, _ = mine
    cfg["providers"]["mine"]["can_edit"] = False
    with pytest.raises(SystemExit, match="cannot edit"):
        Pipeline(project, cfg, log, Runner(project, cfg, log)).preflight()
    cfg["providers"]["mine"]["can_edit"] = True
    cfg["roles"]["builder"] = {"cli": "ghost"}
    with pytest.raises(SystemExit, match="not defined"):
        Pipeline(project, cfg, log, Runner(project, cfg, log)).preflight()


def test_custom_provider_changes_trust(cfg):
    from orch import trust
    before = trust._digest(cfg)
    cfg["providers"] = {"x": {"cmd": ["x"]}}
    assert trust._digest(cfg) != before


def test_registry_merges_presets_and_user(cfg):
    cfg["providers"] = {"codex": {"models": ["gpt-x"]}, "new": {"cmd": ["newai"]}}
    reg = providers.registry(cfg)
    assert reg["codex"]["cmd"] == ["codex", "exec"] and "gpt-x" in reg["codex"]["models"]
    assert reg["new"]["exe"] == "newai" and reg["new"]["can_edit"] is True
    argv, stdin = providers.build_argv(reg["codex"], "gpt-x", "hi", "read")
    assert argv[1:] == ["exec", "-m", "gpt-x", "--sandbox", "read-only", "-"] and stdin == "hi"


def test_suggester_can_be_any_ai_but_a_custom_one_needs_trust(project, mine):
    from orch import config, suggest, trust
    cfg, calls = mine
    config.write_raw(project, {"providers": cfg["providers"], "roles": {"suggester": {"cli": "mine", "model": "big"}}})
    ask = suggest.asker(project)
    assert ask("hi") is None and not records(calls)                     # defined by the repo, not approved yet: never started
    trust.trust(project, config.load(project))
    assert ask("hi") == "ok"
    assert records(calls)[0]["argv"] == ["--m", "big", "--ro"]
