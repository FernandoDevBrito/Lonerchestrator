"""Introduction: find the AIs this computer is logged in to, then let the user assign agents/models to the roles."""
import json
import shutil
import subprocess
import time
from pathlib import Path

from . import folder, providers

CLAUDE_MODELS = ["sonnet", "opus", "haiku"]


def parse_agy_models(text):
    """`agy models` prints 'id<TAB>label' lines after a 'Fetching...' line."""
    return [ln.split("\t")[0].strip() for ln in text.splitlines() if "\t" in ln]


def _run(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        return r.returncode, r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def detect(cfg=None):
    """{ai id: {installed, logged_in, models}} for Claude Code, Antigravity and every other AI in the registry (presets + config `providers`).
    Claude and Antigravity prove their login with a tiny real call. For any other CLI, being installed is enough: if it is not signed in, its own error shows on first use."""
    ais = {}
    exe = shutil.which("claude")
    ok = bool(exe) and _run([exe, "-p", "reply with the word ok"], 90)[0] == 0
    ais["claude"] = {"installed": bool(exe), "logged_in": ok, "models": CLAUDE_MODELS if ok else []}
    exe = shutil.which("agy")
    rc, out = _run([exe, "models"], 60) if exe else (1, "")
    models = parse_agy_models(out) if rc == 0 else []
    ais["agy"] = {"installed": bool(exe), "logged_in": bool(models), "models": models}
    for pid, spec in providers.registry(cfg).items():
        if pid in ais or spec.get("native"):
            continue
        here = bool(shutil.which(spec["exe"]))
        found = providers.list_models(spec) if here else []
        models = list(dict.fromkeys(found + [m for m in spec["models"]])) if here else []
        ais[pid] = {"installed": here, "logged_in": here and bool(models), "models": models, "name": spec["name"]}
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
