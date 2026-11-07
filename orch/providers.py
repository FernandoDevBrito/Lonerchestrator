"""Registry of the AI CLIs lonerchestrator can drive: built-in presets plus ANY CLI the user describes in config (`providers`).
Anything that takes a prompt and prints an answer can play any role.

A provider is a dict:
    cmd          base command, e.g. ["codex", "exec"]
    model_args   added when a model is chosen, "{model}" is replaced, e.g. ["-m", "{model}"]
    extra_args   always added
    edit_args    added when the role must edit project files (planner, builder, retro, splitter)
    read_args    added when the role must only read (reviewers, suggestions)
    prompt_via   "arg" (default: the prompt is the last argument) or "stdin"
    prompt_flag  flag placed before the prompt when prompt_via is "arg", e.g. "-p"
    stdin_marker args added when the prompt comes from stdin, e.g. ["-"]
    output       "text" (default) or "agy-json"
    can_edit     False for text-only models (they can review and suggest, not build)
    models       model names to offer ("default" = do not pass a model)
    models_cmd   command that lists models; models_style how to read it: "lines" | "tab" | "table"
Claude Code is native (its agents, permissions and stream are used directly), the rest go through this description."""
import copy
import json
import shutil
import subprocess

DEFAULT_MODEL = "default"

PRESETS = {
    "claude": {"name": "Claude Code", "exe": "claude", "native": True, "can_edit": True, "models": ["sonnet", "opus", "haiku"], "tested": True},
    "agy": {"name": "Antigravity CLI", "exe": "agy", "cmd": ["agy"], "model_args": ["--model", "{model}"], "extra_args": ["--output-format", "json"],
            "prompt_flag": "-p", "edit_args": ["--mode", "accept-edits"], "read_args": [], "output": "agy-json", "can_edit": True, "models": [],
            "models_cmd": ["agy", "models"], "models_style": "tab", "tested": True},
    "codex": {"name": "OpenAI Codex CLI", "exe": "codex", "cmd": ["codex", "exec"], "model_args": ["-m", "{model}"],
              "edit_args": ["--sandbox", "workspace-write"], "read_args": ["--sandbox", "read-only"],
              "prompt_via": "stdin", "stdin_marker": ["-"], "can_edit": True, "models": [DEFAULT_MODEL], "tested": False},
    "gemini": {"name": "Gemini CLI", "exe": "gemini", "cmd": ["gemini"], "model_args": ["-m", "{model}"],
               "edit_args": ["--approval-mode", "auto_edit"], "read_args": ["--approval-mode", "plan"], "prompt_flag": "-p",
               "can_edit": True, "models": [DEFAULT_MODEL], "tested": False},
    "ollama": {"name": "Ollama (local models)", "exe": "ollama", "cmd": ["ollama", "run"], "model_args": ["{model}"], "prompt_via": "stdin",
               "can_edit": False, "models": [], "models_cmd": ["ollama", "list"], "models_style": "table", "tested": False},
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


def custom_part(cfg):
    """The providers the USER defined in config: they run commands, so they take part in the trust approval."""
    return (cfg or {}).get("providers") or {}


def installed(spec, which=shutil.which):
    return which(spec["exe"])


def build_argv(spec, model, prompt, mode):
    """(argv, stdin_text) for one call. mode is "edit" (may change project files) or "read" (must not)."""
    if spec.get("native"):
        raise ValueError(f"{spec['id']} is native: it is driven by its own runner")
    if mode == "edit" and not spec["can_edit"]:
        raise ValueError(f"{spec['name']} cannot edit files: use it for reviewing and suggestions")
    argv = list(spec["cmd"])
    if model and model != DEFAULT_MODEL:
        argv += [a.replace("{model}", model) for a in spec.get("model_args", [])]
    argv += spec.get("extra_args", [])
    argv += spec.get("edit_args" if mode == "edit" else "read_args", [])
    if spec["prompt_via"] == "stdin":
        argv += spec.get("stdin_marker", [])
        stdin = prompt
    else:
        argv += ([spec["prompt_flag"]] if spec.get("prompt_flag") else []) + [prompt]
        stdin = None
    argv[0] = shutil.which(argv[0]) or argv[0]
    return argv, stdin


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
    return raw.strip(), None


def parse_models(text, style):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if style == "tab":
        return [ln.split("\t")[0].strip() for ln in lines if "\t" in ln]
    if style == "table":
        return [ln.split()[0] for ln in lines[1:]]
    return [ln.split()[0] for ln in lines]


def list_models(spec, run=subprocess.run):
    """Models the installed CLI reports, else []."""
    if not spec.get("models_cmd"):
        return []
    try:
        r = run(spec["models_cmd"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_models(r.stdout, spec.get("models_style", "lines")) if r.returncode == 0 else []


def run_text(spec, model, prompt, mode="read", cwd=None, timeout=300, run=subprocess.run):
    """One simple call that returns the answer text, or None when it failed. Used where no live output is needed (suggestions)."""
    argv, stdin = build_argv(spec, model, prompt, mode)
    try:
        kw = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        r = run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False, **kw)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_output(spec, r.stdout)[0] if r.returncode == 0 else None
