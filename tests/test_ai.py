"""The AI objects (Strategy): one place knows how each kind of AI is called."""
from orch import ai, providers


class Run:
    """Records which runner method an AI chose and with what."""

    def __init__(self):
        self.calls = []

    def claude(self, *a, **kw):
        self.calls.append(("claude", a, kw))
        return "c"

    def provider(self, *a, **kw):
        self.calls.append(("provider", a, kw))
        return "p"


def test_registry_has_one_object_per_ai_and_only_claude_is_native():
    reg = ai.registry({"providers": {"mine": {"cmd": ["my-ai"]}}})
    assert isinstance(reg["claude"], ai.ClaudeCode) and reg["claude"].native
    assert all(isinstance(reg[k], ai.GenericCLI) and not reg[k].native for k in ("agy", "codex", "gemini", "ollama", "mine"))
    assert reg["mine"].name == "mine" and reg["mine"].spec["exe"] == "my-ai" and not reg["ollama"].can_edit and reg["agy"].can_edit


def test_claude_uses_its_own_agents_and_others_get_the_role_text_in_the_prompt():
    run, ins = Run(), lambda agent: f"[{agent} rules] "
    ai.registry()["claude"].call(run, "builder", "backend", "sonnet", "do it", "edit", ins)
    ai.registry()["codex"].call(run, "builder", "backend", "default", "do it", "edit", ins)
    assert run.calls[0] == ("claude", ("builder", "backend", "do it"), {"model": "sonnet"})
    assert run.calls[1] == ("provider", ("builder", "codex", "default", "[backend rules] do it", "edit"), {})


def test_a_non_claude_reviewer_gets_the_review_inlined_and_read_only(tmp_path):
    f = tmp_path / "review1.txt"
    f.write_text("# CARD\nthe diff", encoding="utf-8")
    run, ins = Run(), lambda agent: "[qa] "
    ai.registry()["gemini"].review(run, "cross", "qa", "m", "001", f, ins)
    ai.registry()["claude"].review(run, "qa", "qa", "sonnet", "001", f, ins)
    kind, args, _ = run.calls[0]
    assert kind == "provider" and args[4] == "read" and "the diff" in args[3] and "Do not run commands" in args[3]
    assert run.calls[1][0] == "claude" and str(f.as_posix()) in run.calls[1][1][2]                # Claude reads the file itself


def test_ask_goes_through_the_right_door(monkeypatch):
    from orch import suggest
    monkeypatch.setattr(suggest, "ask_claude", lambda prompt, cwd=None, model="x": f"claude:{model}")
    monkeypatch.setattr(providers, "run_text", lambda spec, model, prompt, mode, cwd=None, **k: f"{spec['id']}:{mode}")
    reg = ai.registry()
    assert reg["claude"].ask(None, "q") == "claude:haiku" and reg["codex"].ask("m", "q") == "codex:read"


def test_how_to_get_each_ai_ready_lives_in_the_presets():
    reg = providers.registry()
    assert reg["claude"]["install_hint"].startswith("install: https://claude.com") and reg["claude"]["url"]
    assert "antigravity.google" in reg["agy"]["install_hint"] and "`agy`" in reg["agy"]["login_hint"]
    assert reg["codex"]["install_hint"] == "install `codex`" and "ollama pull" in reg["ollama"]["login_hint"]
