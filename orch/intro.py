"""Introduction: find the AIs this computer can use, then let the user assign agents/models to the roles."""
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from . import folder, providers


def _get(url, body=None):
    """JSON from a model server on this computer, or None when nothing answers. Never through a proxy: the server is local."""
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=2) as r:       # nosec B310: preset or trusted URL
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def server_models(base, get=_get):
    """The models a local server offers to an agent, or None when it is not running. Ollama says which ones can use tools (an agent cannot
    work without them); an OpenAI-style server (LM Studio) only lists ids, so all but embedding models are offered."""
    tags = get(base + "/api/tags")
    if tags is not None:
        names = [m["name"] for m in tags.get("models", []) if m.get("name")]
        return [n for n in names if "tools" in ((get(base + "/api/show", {"model": n}) or {}).get("capabilities") or [])]
    data = get(base + "/v1/models")
    return None if data is None else [m["id"] for m in data.get("data", []) if m.get("id") and "embed" not in m["id"].lower()]


def detect(cfg=None, which=shutil.which, run=subprocess.run, get=_get, environ=os.environ):
    """{ai id: {name, installed, logged_in, models, why?, unchecked?}} for every AI in the registry (presets + config `providers`), each found
    the cheapest way that proves it, never by asking a model:
        server      a model server on this computer answers (Ollama, LM Studio): its models that can use tools
        key_env     the API-key variable is set (only that it is set: the value is not read here)
        status_cmd  the CLI's own sign-in check passes (Claude Code, Codex)
        models_cmd  the CLI lists models, which it only can when signed in (Antigravity, Ollama)
    Any other installed CLI is offered with its models and marked `unchecked`: if it is not signed in, its own error shows on first use.
    `installed` is False for a server that does not answer or a key that is not set, so only what is really here is listed.
    `why` says what is missing, for the panel and `doctor`."""
    ais = {}
    for pid, spec in providers.registry(cfg).items():
        rec, ok = {"name": spec["name"], "installed": bool(which(spec["exe"])), "models": list(spec["models"])}, True
        if not rec["installed"]:
            ok = False
        elif spec.get("server"):
            found = server_models(spec["server"], get)
            rec["installed"], rec["models"] = found is not None, found or []
            if not found:
                rec["why"] = ("no model here can use tools: " if found is not None else f"nothing answers at {spec['server']}: ") + spec["login_hint"]
        elif key := providers.missing_key(spec, environ):
            rec["installed"], rec["why"] = False, f"set {key} in your environment (your key from {spec.get('url', 'its website')}), then press d"
        elif spec.get("status_cmd"):
            ok = providers.signed_in(spec, run)
        elif spec.get("models_cmd"):
            rec["models"] = list(dict.fromkeys(providers.list_models(spec, run) + rec["models"]))
        else:
            rec["unchecked"] = True
        rec["logged_in"] = rec["installed"] and ok and bool(rec["models"])
        if rec["installed"] and not rec["logged_in"]:
            rec.setdefault("why", spec["login_hint"])
        ais[pid] = rec
    return ais


def save_ais(project, ais):
    """Remember what detect() found: ais.json in the project's folder (read by the panel and the AIs menu)."""
    d = folder.of(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / "ais.json").write_text(json.dumps({"ts": time.strftime("%F %T"), "ais": ais}, indent=2), encoding="utf-8")


def _pick(title, options, default, ask, out):
    """options: list of (label, value). Returns value. Blank answer = default index."""
    out(f"\n{title}")
    for i, (label, _) in enumerate(options, 1):
        out(f"  {i}) {label}{'   <- default' if i - 1 == default else ''}")
    while True:
        try:
            a = ask(f"  choose [1-{len(options)}, enter={default + 1}]: ").strip()
        except EOFError:        # no terminal attached: take the default
            return options[default][1]
        if not a:
            return options[default][1]
        if a.isdigit() and 1 <= int(a) <= len(options):
            return options[int(a) - 1][1]


def run_intro(project, ask=input, out=print, assume_yes=False, ais=None):
    """Detect AIs, assign roles, write config.json + ais.json in the project's folder. Returns the new raw config."""
    from . import config, tui
    project = Path(project)
    cfg = config.load(project)
    out("\n=== ORCH introduction: AIs on this computer ===")
    ais = ais or detect(cfg)
    for name, v in ais.items():
        if not v["installed"] and name not in ("claude", "agy"):
            continue                                  # do not list every preset the user never installed
        state = "logged in" if v["logged_in"] else ("installed, NOT logged in" if v["installed"] else "not installed")
        out(f"  {name:<8} {state:<26} {', '.join(v['models'][:6])}{' ...' if len(v['models']) > 6 else ''}")
    save_ais(project, ais)
    reg = providers.registry(cfg)
    live = [(c, m) for c, v in ais.items() if v["logged_in"] for m in v["models"]]
    edit = [(c, m) for c, m in live if reg.get(c, {}).get("can_edit", c in ("claude", "agy"))]
    if not edit:
        out("\nNo AI that can edit files is ready. Run `lonerchestrator ais` to install one (Claude Code is the best tested), log in, then `lonerchestrator intro` again.")
        return None
    claude_opts = [(f"{c} / {m}", (c, m)) for c, m in edit]
    all_opts = [(f"{c} / {m}", (c, m)) for c, m in live]

    def default_idx(opts, cur):
        return next((i for i, (_, v) in enumerate(opts) if v == cur), 0)

    new = {"roles": {}, "reviewers": [], "agents": dict(cfg["agents"])}
    for role in ("splitter", "planner", "builder", "retro"):
        cur = (cfg["roles"][role].get("cli", "claude"), cfg["roles"][role]["model"])
        cli, m = claude_opts[default_idx(claude_opts, cur)][1] if assume_yes else _pick(f"{role}: which AI and model?", claude_opts, default_idx(claude_opts, cur), ask, out)
        new["roles"][role] = {"cli": cli, "model": m}
    for slot, r in zip(("qa", "cross"), cfg["reviewers"], strict=False):
        cur = (r["kind"], r.get("model"))
        opts = all_opts
        i = default_idx(opts, cur)
        first_agy = next((k for k, (_, v) in enumerate(opts) if v[0] == "agy"), None)
        if slot == "cross" and first_agy is not None and (cur[0] == "claude" or cur not in [v for _, v in opts]):
            i = first_agy              # a different model family catches different mistakes
        kind, model = opts[i][1] if assume_yes else _pick(f"reviewer '{slot}' (independent of the builder, should be a DIFFERENT model): which AI?", opts, i, ask, out)
        new["reviewers"].append({"name": slot, "kind": kind, "model": model, "required": True, **({"agent": "qa"} if kind == "claude" else {})})
    a, b = new["reviewers"]
    if (a["kind"], a["model"]) == (b["kind"], b["model"]):
        out("\n  note: both reviewers use the same model, cross-review is weaker.")
    agents_dir = folder.of(project) / "agents"
    have = sorted(p.stem for p in agents_dir.glob("*.md") if p.stem not in ("qa", "retro", "splitter")) if agents_dir.exists() else []
    for area in ("backend", "frontend", "both"):
        if have and not assume_yes:
            cur = cfg["agents"][area]
            new["agents"][area] = _pick(f"area '{area}': which agent implements it?", [(a, a) for a in have], have.index(cur) if cur in have else 0, ask, out)

    raw = config.read_raw(project)
    raw.update(new)
    in_use = [f"{r['cli']}/{r['model']}" for r in new["roles"].values()] + [f"{r['kind']}/{r['model']}" for r in new["reviewers"]]
    raw["use"] = sorted(set(raw.get("use") or []) | set(in_use))      # the AIs menu (tab 5) lets you check more
    config.write_raw(project, raw)
    out("\nSaved the config. This is your pipeline:\n")
    out(tui.render(project, screen=1))
    return raw


def configured(project):
    from . import config
    return "roles" in config.read_raw(project)
