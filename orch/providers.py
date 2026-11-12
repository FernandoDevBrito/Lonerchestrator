"""Registry of the AI CLIs lonerchestrator can drive: built-in presets plus ANY CLI the user describes in config (`providers`).
Anything that takes a prompt and prints an answer can play any role.

A provider is a dict:
    cmd          base command, e.g. ["codex", "exec"]
    model_args   added when a model is chosen, "{model}" is replaced, e.g. ["-m", "{model}"]
    extra_args   always added
    edit_args    added when the role must edit project files (planner, builder, retro, splitter)
    read_args    added when the role must only read (reviewers, suggestions)
    dir_args     added once per folder outside the project the agent works with (its card's board, context, memory, the run's files),
                 "{dir}" is replaced, e.g. ["--add-dir", "{dir}"]; a CLI without them must be able to reach those paths by itself
    prompt_via   "arg" (default: the prompt is the last argument) or "stdin"
    prompt_flag  flag placed before the prompt when prompt_via is "arg", e.g. "-p"
    stdin_marker args added when the prompt comes from stdin, e.g. ["-"]
    output       "text" (default) or "agy-json"
    effort_args  added when a role sets `effort` (how hard the model thinks), "{effort}" is replaced, e.g. ["-c", "model_reasoning_effort={effort}"]
    efforts      the effort words this CLI accepts; a higher one asked for is lowered to its highest (no list = passed as given, no effort_args = ignored)
    can_edit     False for text-only models (they can review and suggest, not build)
    models       model names to offer ("default" = do not pass a model)
    models_cmd   command that lists models; models_style how to read it: "lines" | "tab" | "table"
    status_cmd   the CLI's own sign-in check, exit code 0 = signed in (no model call), e.g. ["claude", "auth", "status"]
    server       a local model server (Ollama, LM Studio): found by asking it over HTTP; its models are the ones it serves
    key_env      the environment variable that holds this AI's API key: ready when it is set (the value is only ever given to that AI)
    env          (Claude Code providers) environment for Claude Code, "$VAR" taken from yours: see claude_env
    url, install_hint, login_hint   where to get it and how to make it ready: shown by the panel, the web page and the readiness checks
    usage        how to read the tokens the CLI prints (see extract_usage); without it the runner estimates (about 4 characters per token)
    strip_after  text after which the CLI prints statistics, cut from the answer
    price        {"in": usd, "out": usd} per million tokens: turns tokens into an estimated cost
Claude Code is native (its agents, permissions and stream are used directly). A native provider with `server` or `env` is Claude Code
talking to another model server through its Anthropic-compatible API: the same agents, tools and edits, another model. The rest go through
this description."""
import copy
import json
import os
import re
import shutil
import subprocess

DEFAULT_MODEL = "default"
EFFORTS = ["low", "medium", "high", "xhigh", "max"]                    # the words a role's `effort` may use (Claude Code's own scale)
MODEL_VARS = ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
              "ANTHROPIC_DEFAULT_FABLE_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL")


def _via_claude(name, url, base=None, key_env=None, **spec):
    """A model server or API that speaks Anthropic's protocol, driven by Claude Code. `base`: its address, the key from `key_env`."""
    # shortcut: model ids are the ones each vendor documents today; they rename them often, so users add new ones under `providers`
    env ={"ANTHROPIC_BASE_URL": base, "ANTHROPIC_AUTH_TOKEN": f"${key_env}"} if key_env else {}
    return {"name": name, "exe": "claude", "native": True, "can_edit": True, "url": url, "efforts": [], "tested": False, "env": env,
            "install_hint": "needs Claude Code: run `lonerchestrator ais`", **({"key_env": key_env} if key_env else {}),
            "login_hint": f"set {key_env} in your environment (your key from {url}), then press d" if key_env else "", **spec}


PRESETS = {
    "claude": {"name": "Claude Code", "exe": "claude", "native": True, "can_edit": True, "models": ["sonnet", "opus", "haiku"], "tested": True,
               "efforts": EFFORTS, "url": "https://claude.com/claude-code", "install_hint": "install: https://claude.com/claude-code",
               "status_cmd": ["claude", "auth", "status"]},
    "agy": {"name": "Antigravity CLI", "exe": "agy", "install_hint": "optional, Gemini models: antigravity.google", "cmd": ["agy"], "model_args": ["--model", "{model}"], "extra_args": ["--output-format", "json"],
            "prompt_flag": "-p", "edit_args": ["--mode", "accept-edits"], "read_args": [], "output": "agy-json", "can_edit": True, "models": [],
            "models_cmd": ["agy", "models"], "models_style": "tab", "tested": True},
    "codex": {"name": "OpenAI Codex CLI", "exe": "codex", "cmd": ["codex", "exec"], "model_args": ["-m", "{model}"],
              "edit_args": ["--sandbox", "workspace-write"], "read_args": ["--sandbox", "read-only"], "dir_args": ["--add-dir", "{dir}"],
              "effort_args": ["-c", "model_reasoning_effort={effort}"], "efforts": ["low", "medium", "high"],
              "prompt_via": "stdin", "stdin_marker": ["-"], "can_edit": True, "models": [DEFAULT_MODEL], "tested": False,
              "usage": {"total_regex": r"tokens used\D+([\d,]+)"}, "status_cmd": ["codex", "login", "status"]},
    "gemini": {"name": "Gemini CLI", "exe": "gemini", "cmd": ["gemini"], "model_args": ["-m", "{model}"],
               "edit_args": ["--approval-mode", "auto_edit"], "read_args": ["--approval-mode", "plan"], "prompt_flag": "-p",
               "dir_args": ["--include-directories", "{dir}"],
               "can_edit": True, "models": [DEFAULT_MODEL], "tested": False},
    "ollama": {"name": "Ollama (local models)", "exe": "ollama", "cmd": ["ollama", "run"], "model_args": ["{model}"], "prompt_via": "stdin",
               "can_edit": False, "models": [], "models_cmd": ["ollama", "list"], "login_hint": "run `ollama pull <model>` once, then press d", "models_style": "table", "tested": False,
               "extra_args": ["--verbose"], "strip_after": "total duration:",
               "usage": {"in_regex": r"prompt eval count:\s*(\d+)", "out_regex": r"(?<!prompt )eval count:\s*(\d+)"}},
    # agent CLIs, flags from each vendor's docs (not run by the author)
    "grok": {"name": "Grok Build", "exe": "grok", "cmd": ["grok", "--no-auto-update"], "prompt_flag": "-p", "model_args": ["-m", "{model}"],
             "edit_args": ["--always-approve"], "read_args": [], "effort_args": ["--effort", "{effort}"], "models": [DEFAULT_MODEL],
             "url": "https://docs.x.ai/build/overview", "login_hint": "run `grok` once and sign in (SuperGrok or X Premium+), or set XAI_API_KEY, then press d"},
    "copilot": {"name": "GitHub Copilot CLI", "exe": "copilot", "cmd": ["copilot", "-s", "--no-ask-user"], "prompt_flag": "-p",
                "model_args": ["--model={model}"], "edit_args": ["--allow-all-tools"], "read_args": ["--deny-tool=write, shell"],
                "dir_args": ["--add-dir={dir}"], "models": [DEFAULT_MODEL], "url": "https://docs.github.com/en/copilot/how-tos/copilot-cli",
                "login_hint": "run `copilot` once and sign in with GitHub (needs a Copilot plan), then press d"},
    "cursor": {"name": "Cursor CLI", "exe": "cursor-agent", "cmd": ["cursor-agent", "--output-format", "text"], "prompt_flag": "-p",
               "edit_args": ["--force"], "read_args": [], "models": [DEFAULT_MODEL], "url": "https://cursor.com/docs/cli/headless",
               "login_hint": "run `cursor-agent` once and sign in, or set CURSOR_API_KEY, then press d"},     # without --force it only proposes changes
    # model servers and APIs that speak Anthropic's protocol: Claude Code drives them (agents, tools, edits), only the model changes
    "ollama-claude": _via_claude("Ollama models in Claude Code", "https://docs.ollama.com/integrations/claude-code", server="http://localhost:11434",
                                 env={"ANTHROPIC_AUTH_TOKEN": "ollama"}, models=[],
                                 login_hint="start Ollama 0.14 or newer and pull a model that can use tools, then press d"),
    "lmstudio": _via_claude("LM Studio in Claude Code", "https://lmstudio.ai/docs/integrations/claude-code", server="http://localhost:1234",
                            env={"ANTHROPIC_AUTH_TOKEN": "lmstudio"}, models=[],
                            login_hint="start LM Studio 0.4.1 or newer with its server on and a model downloaded, then press d"),
    "minimax": _via_claude("MiniMax in Claude Code", "https://platform.minimax.io/docs/coding-plan/claude-code", "https://api.minimax.io/anthropic",
                           "MINIMAX_API_KEY", models=["MiniMax-M3.1-Flash"], efforts=EFFORTS),
    "deepseek": _via_claude("DeepSeek in Claude Code", "https://api-docs.deepseek.com/guides/anthropic_api", "https://api.deepseek.com/anthropic",
                            "DEEPSEEK_API_KEY", models=["deepseek-v4-pro", "deepseek-flash"]),
    "zai": _via_claude("Z.ai GLM in Claude Code", "https://docs.z.ai/devpack/tool/claude", "https://api.z.ai/api/anthropic", "ZAI_API_KEY",
                       models=["glm-5.3", "glm-5.3-flash"]),
    "kimi": _via_claude("Kimi in Claude Code", "https://platform.kimi.ai/docs/guide/claude-code-kimi", "https://api.moonshot.ai/anthropic",
                        "MOONSHOT_API_KEY", models=["kimi-k3"]),
    "openrouter": _via_claude("OpenRouter in Claude Code", "https://openrouter.ai/docs/cookbook/coding-agents/claude-code-integration",
                              "https://openrouter.ai/api", "OPENROUTER_API_KEY", models=[],            # hundreds of models: you pick
                              login_hint='add the model ids you want to the config: "providers": {"openrouter": {"models": [...]}}, then press d'),
}


def _normalize(pid, spec):
    spec["id"] = pid
    spec.setdefault("name", pid)
    spec.setdefault("exe", (spec.get("cmd") or [pid])[0])
    spec.setdefault("output", "text")
    spec.setdefault("prompt_via", "arg")
    spec.setdefault("can_edit", True)
    spec.setdefault("models", [DEFAULT_MODEL])
    spec.setdefault("tested", False)
    spec.setdefault("install_hint", f"install `{spec['exe']}`")           # shown where the panel says how to get this AI ready: one place, not one per screen
    spec.setdefault("login_hint", f"run `{spec['exe']}`, log in, then press d")
    return spec


def registry(cfg=None):
    """{id: spec}: the presets, then providers from config. A config entry for a preset id changes it (its `models` are ADDED to the preset's)."""
    reg = {pid: _normalize(pid, copy.deepcopy(spec)) for pid, spec in PRESETS.items()}
    for pid, user in ((cfg or {}).get("providers") or {}).items():
        base = reg.get(pid, {})
        spec = {**copy.deepcopy(base), **user}
        if "models" in user:
            spec["models"] = list(dict.fromkeys(list(base.get("models", [])) + list(user["models"])))
        reg[pid] = _normalize(pid, spec)
    return reg


def effort_for(spec, effort):
    """The effort word to pass to this CLI: None when no effort is set or the CLI has no way to take one; lowered to the CLI's highest when above it."""
    allowed = spec.get("efforts")
    if not effort or not (spec.get("native") or spec.get("effort_args")) or allowed == []:          # [] = takes no effort
        return None
    return effort if not allowed or effort in allowed else allowed[-1]


def missing_key(spec, environ=os.environ):
    """The API-key variable this provider needs and your environment lacks, else None."""
    k = spec.get("key_env")
    return k if k and not environ.get(k) else None


def via_claude(spec):
    """Claude Code talking to another model server (see claude_env)."""
    return bool(spec.get("native") and (spec.get("server") or spec.get("env")))


def claude_env(spec, model, environ=os.environ):
    """The environment for Claude Code talking to another server. `$VAR` values come from yours, so keys never sit in config.json;
    ANTHROPIC_BASE_URL defaults to `server`; your own Anthropic credentials are blanked (a dummy token keeps Claude Code from falling back
    to your login), so they never reach that server; every model alias points at `model`, so no claude-* name is sent to it."""
    env = {**environ, "ANTHROPIC_API_KEY": "", "CLAUDE_CODE_OAUTH_TOKEN": "", "ANTHROPIC_AUTH_TOKEN": "none",
           **({"ANTHROPIC_BASE_URL": spec["server"]} if spec.get("server") else {})}
    env.update({k: re.sub(r"\$\{?(\w+)\}?", lambda m: environ.get(m.group(1), ""), str(v)) for k, v in (spec.get("env") or {}).items()})
    if model and model != DEFAULT_MODEL:
        env.update(dict.fromkeys(MODEL_VARS, model))
    return env


def build_argv(spec, model, prompt, mode, effort=None, dirs=()):
    """(argv, stdin_text) for one call. mode is "edit" (may change project files) or "read" (must not). `dirs`: the folders outside the
    project the agent works with (see dir_args)."""
    if spec.get("native"):
        raise ValueError(f"{spec['id']} is native: it is driven by its own runner")
    if mode == "edit" and not spec["can_edit"]:
        raise ValueError(f"{spec['name']} cannot edit files: use it for reviewing and suggestions")
    argv = list(spec["cmd"])
    if model and model != DEFAULT_MODEL:
        argv += [a.replace("{model}", model) for a in spec.get("model_args", [])]
    if e := effort_for(spec, effort):
        argv += [a.replace("{effort}", e) for a in spec["effort_args"]]
    argv += spec.get("extra_args", [])
    argv += spec.get("edit_args" if mode == "edit" else "read_args", [])
    for d in dirs:
        argv += [a.replace("{dir}", str(d)) for a in spec.get("dir_args", [])]
    if spec["prompt_via"] == "stdin":
        argv += spec.get("stdin_marker", [])
        stdin = prompt
    else:
        argv += ([spec["prompt_flag"]] if spec.get("prompt_flag") else []) + [prompt]
        stdin = None
    argv[0] = shutil.which(argv[0]) or argv[0]
    return argv, stdin


def _num(text):
    return int(re.sub(r"\D", "", str(text)) or 0)


def _dig(obj, path):
    """obj["a"]["b"][0] for the path "a.b.0"; None when something is missing."""
    for part in str(path).split("."):
        try:
            obj = obj[int(part)] if isinstance(obj, list) else obj[part]
        except (KeyError, IndexError, ValueError, TypeError):
            return None
    return obj


def extract_usage(spec, raw):
    """Tokens a CLI reports about itself, found the way the provider's `usage` setting says. None when nothing is found.

        "usage": {"json": {"in": "usage.input_tokens", "out": "usage.output_tokens"}}     the output is one JSON object
        "usage": {"in_regex": "input: (\\d+)", "out_regex": "output: (\\d+)"}               numbers anywhere in the output (stderr included)
        "usage": {"total_regex": "tokens used\\D+([\\d,]+)"}                                  only a total is printed
    Anything missing is estimated by the runner instead (about 4 characters per token), and flagged as an estimate."""
    spec_u = spec.get("usage") or {}
    found = {}
    if "json" in spec_u:
        try:
            obj = json.loads(raw)
            for k in ("in", "out"):
                v = _dig(obj, spec_u["json"].get(k, ""))
                if isinstance(v, (int, float)):
                    found[k] = int(v)
        except ValueError:
            pass
    for k, key in (("in", "in_regex"), ("out", "out_regex")):
        if key in spec_u and (m := re.search(spec_u[key], raw)):
            found[k] = _num(m.group(1))
    if "total_regex" in spec_u and (m := re.search(spec_u["total_regex"], raw)):
        found.setdefault("in", 0)
        found.setdefault("out", _num(m.group(1)))
    return {"in": found.get("in", 0), "out": found.get("out", 0), "secs": 0} if found else None


def parse_output(spec, raw):
    """(answer_text, usage) from what the CLI printed. usage is {"in": n, "out": n, "secs": s} or None when the CLI does not report it."""
    if spec["output"] == "agy-json":
        try:
            obj = json.loads(raw)
            u = obj.get("usage") or {}
            return obj.get("response", ""), {"in": u.get("input_tokens", 0) + u.get("cache_read_tokens", 0), "out": u.get("output_tokens", 0),
                                             "secs": obj.get("duration_seconds", 0)}
        except (ValueError, AttributeError):
            pass
    answer = raw
    if spec.get("strip_after") and spec["strip_after"] in raw:           # statistics some CLIs print after the answer
        answer = raw.split(spec["strip_after"], 1)[0]
    return answer.strip(), extract_usage(spec, raw)


def parse_models(text, style):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if style == "tab":
        return [ln.split("\t")[0].strip() for ln in lines if "\t" in ln]
    if style == "table":
        return [ln.split()[0] for ln in lines[1:]]
    return [ln.split()[0] for ln in lines]


def _quick(cmd, run):
    """Run a short CLI command (a model list, a sign-in check): the finished process, or None. npm installs a .cmd that only a full path runs."""
    try:
        return run([shutil.which(cmd[0]) or cmd[0], *cmd[1:]], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                   check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def list_models(spec, run=subprocess.run):
    """Models the installed CLI reports, else []."""
    r = _quick(spec["models_cmd"], run) if spec.get("models_cmd") else None
    return parse_models(r.stdout, spec.get("models_style", "lines")) if r and r.returncode == 0 else []


def signed_in(spec, run=subprocess.run):
    """The CLI's own sign-in check (status_cmd) passed. Asks no model."""
    r = _quick(spec["status_cmd"], run)
    return bool(r) and r.returncode == 0


def run_text(spec, model, prompt, mode="read", cwd=None, timeout=300, run=subprocess.run):
    """One simple call that returns the answer text, or None when it failed. Used where no live output is needed (suggestions)."""
    argv, stdin = build_argv(spec, model, prompt, mode)
    try:
        kw = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        r = run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False, **kw)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_output(spec, r.stdout)[0] if r.returncode == 0 else None
