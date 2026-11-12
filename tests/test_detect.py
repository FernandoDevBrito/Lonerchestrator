"""Every AI on this computer is found the cheapest way that proves it (never by asking a model), and the model servers and APIs found
are driven by Claude Code with an environment that keeps your own credentials away from them."""
import json
import os
import sys
import time

from orch import agents, config, intro, providers, suggest, usage


class Proc:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout = rc, out


def machine(asked):
    """A pretend computer: what is on PATH, what each CLI answers, which local servers run."""
    answers = {"claude auth status": Proc(0), "codex login status": Proc(1), "agy models": Proc(0, "Fetching models...\ngem-x\tGem X\n")}

    def run(cmd, **kw):
        line = " ".join([os.path.basename(cmd[0]).split(".")[0], *cmd[1:]])
        asked.append(line)
        return answers.get(line, Proc(1))

    def get(url, body=None):
        if url == "http://localhost:11434/api/tags":
            return {"models": [{"name": "qwen3-coder"}, {"name": "llama3"}]}
        if url == "http://localhost:11434/api/show":
            return {"capabilities": ["completion", "tools"] if body["model"] == "qwen3-coder" else ["completion"]}
        return None                                                           # nothing on LM Studio's port

    return {"which": lambda exe: f"/bin/{exe}" if exe in ("claude", "agy", "codex", "gemini") else None, "run": run, "get": get,
            "environ": {"MINIMAX_API_KEY": "secret"}}


def test_every_kind_of_ai_is_found_without_asking_a_model():
    asked = []
    ais = intro.detect(**machine(asked))
    assert ais["claude"]["logged_in"] and ais["claude"]["models"] == ["sonnet", "opus", "haiku"]          # `claude auth status` said 0
    assert ais["codex"]["installed"] and not ais["codex"]["logged_in"] and "codex" in ais["codex"]["why"]  # its own check said no
    assert ais["agy"]["logged_in"] and ais["agy"]["models"] == ["gem-x"]
    assert ais["gemini"]["logged_in"] and ais["gemini"]["unchecked"]                                     # no way to check: offered, marked
    assert ais["ollama-claude"]["logged_in"] and ais["ollama-claude"]["models"] == ["qwen3-coder"]       # only models that can use tools
    assert not ais["lmstudio"]["installed"] and "nothing answers at http://localhost:1234" in ais["lmstudio"]["why"]
    assert ais["minimax"]["logged_in"] and not ais["deepseek"]["installed"] and "DEEPSEEK_API_KEY" in ais["deepseek"]["why"]
    assert not ais["grok"]["installed"] and not ais["openrouter"]["installed"]
    assert all(" -p" not in a for a in asked) and "secret" not in json.dumps(ais)                        # no model call, no key stored


def test_a_server_without_tool_models_says_why_and_an_openai_style_server_lists_its_ids():
    m = machine([])
    m["get"] = lambda url, body=None: {"models": [{"name": "llama3"}]} if url.endswith("/api/tags") else {"capabilities": ["completion"]}
    rec = intro.detect(**m)["ollama-claude"]
    assert rec["installed"] and not rec["logged_in"] and "can use tools" in rec["why"]
    lm = {"http://h/v1/models": {"data": [{"id": "qwen3-30b"}, {"id": "text-embedding-nomic"}]}}
    assert intro.server_models("http://h", lambda url, body=None: lm.get(url)) == ["qwen3-30b"]
    assert intro.server_models("http://h", lambda url, body=None: None) is None


def test_claude_env_keeps_your_credentials_away_and_points_every_alias_at_the_model():
    reg = providers.registry()
    mine = {"MINIMAX_API_KEY": "mk", "ANTHROPIC_API_KEY": "my-anthropic-key", "CLAUDE_CODE_OAUTH_TOKEN": "my-oauth", "PATH": "p"}
    env = providers.claude_env(reg["minimax"], "MiniMax-M3.1-Flash", environ=mine)
    assert env["ANTHROPIC_BASE_URL"] == "https://api.minimax.io/anthropic" and env["ANTHROPIC_AUTH_TOKEN"] == "mk" and env["PATH"] == "p"
    assert env["ANTHROPIC_API_KEY"] == "" and env["CLAUDE_CODE_OAUTH_TOKEN"] == ""
    assert all(env[k] == "MiniMax-M3.1-Flash" for k in providers.MODEL_VARS)                          # no claude-* name reaches it
    env = providers.claude_env(reg["ollama-claude"], "qwen3-coder", environ={})
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434" and env["ANTHROPIC_AUTH_TOKEN"] == "ollama"
    env = providers.claude_env({"native": True, "server": "http://box:8080"}, "m", environ={"ANTHROPIC_AUTH_TOKEN": "mine"})
    assert env["ANTHROPIC_AUTH_TOKEN"] == "none"                                                       # your token never goes to a server you added
    assert providers.missing_key(reg["minimax"], {}) == "MINIMAX_API_KEY" and providers.missing_key(reg["minimax"], mine) is None
    assert providers.effort_for(reg["ollama-claude"], "high") is None and providers.effort_for(reg["minimax"], "max") == "max"


def test_claude_code_on_another_server_runs_with_its_env_and_books_usage_to_that_ai(project, cfg, log):
    spec = providers.registry()["ollama-claude"]
    ev = "{'type': 'result', 'duration_ms': 1000, 'result': os.environ['ANTHROPIC_BASE_URL'] + ' ' + os.environ['ANTHROPIC_DEFAULT_HAIKU_MODEL'], " \
         "'modelUsage': {'qwen3-coder': {'inputTokens': 10, 'outputTokens': 5, 'costUSD': 9.9}}}"
    r = agents.Runner(project, cfg, log)
    out = r._run("builder", [sys.executable, "-c", f"import json, os; print(json.dumps({ev}))"], claude=True, spec=spec, model="qwen3-coder")
    assert out == "http://localhost:11434 qwen3-coder"
    assert usage.run_totals(project, log.run_id)["ollama-claude"]["qwen3-coder"] == {"calls": 1, "in": 10, "out": 5, "cost": 0.0}
    assert "claude" not in usage.run_totals(project, log.run_id)                       # not booked (or priced) as your Claude account


def test_a_cli_that_never_answers_is_stopped(project, cfg, log):
    cfg["card_timeout_min"] = 0.02                                                    # about a second
    t = time.time()
    agents.Runner(project, cfg, log)._run("cross", [sys.executable, "-c", "import time; time.sleep(60)"], claude=False)
    assert time.time() - t < 30


def test_a_server_the_repository_defines_needs_trust_before_a_suggestion_goes_there(project, monkeypatch):
    sent = []
    monkeypatch.setattr(suggest, "ask_claude", lambda *a, **kw: sent.append(kw) or "ok")
    monkeypatch.setattr(providers.shutil, "which", lambda exe: f"/bin/{exe}")
    config.write_raw(project, {"providers": {"lan": {"native": True, "server": "http://box:1", "models": ["m"]}},
                               "roles": {"suggester": {"cli": "lan", "model": "m"}}})
    assert suggest.asker(project)("hi") is None and not sent
    from orch import trust
    trust.trust(project, config.load(project))
    assert suggest.asker(project)("hi") == "ok" and sent[0]["env"]["ANTHROPIC_BASE_URL"] == "http://box:1"
