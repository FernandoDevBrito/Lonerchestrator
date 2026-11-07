"""Introduction: find the AIs this computer is logged in to, then let the user assign agents/models to the roles."""
import json
import shutil
import subprocess
import time
from pathlib import Path

CLAUDE_MODELS = ["sonnet", "opus", "haiku"]
UNSUPPORTED = ["gemini", "codex"]   # detected for information only


def parse_agy_models(text):
    """`agy models` prints 'id<TAB>label' lines after a 'Fetching...' line."""
    return [ln.split("\t")[0].strip() for ln in text.splitlines() if "\t" in ln]


def _run(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        return r.returncode, r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def detect():
    """{'claude': {installed, logged_in, models}, 'agy': {...}} (login = a tiny real call succeeds)."""
    ais = {}
    exe = shutil.which("claude")
    ok = bool(exe) and _run([exe, "-p", "reply with the word ok"], 90)[0] == 0
    ais["claude"] = {"installed": bool(exe), "logged_in": ok, "models": CLAUDE_MODELS if ok else []}
    exe = shutil.which("agy")
    rc, out = _run([exe, "models"], 60) if exe else (1, "")
    models = parse_agy_models(out) if rc == 0 else []
    ais["agy"] = {"installed": bool(exe), "logged_in": bool(models), "models": models}
    return ais


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
    """Detect AIs, assign roles, write .orchestrator/config.json + ais.json. Returns the new raw config."""
    from . import config, tui
    project = Path(project)
    cfg = config.load(project)
    out("\n=== ORCH introduction: AIs on this computer ===")
    ais = ais or detect()
    for name, v in ais.items():
        state = "logged in" if v["logged_in"] else ("installed, NOT logged in" if v["installed"] else "not installed")
        out(f"  {name:<8} {state:<26} {', '.join(v['models'][:6])}{' ...' if len(v['models']) > 6 else ''}")
    for name in UNSUPPORTED:
        if shutil.which(name):
            out(f"  {name:<8} detected, not supported as a runner yet")
    (project / ".orchestrator").mkdir(exist_ok=True)
    (project / ".orchestrator" / "ais.json").write_text(json.dumps({"ts": time.strftime("%F %T"), "ais": ais}, indent=2), encoding="utf-8")
    if not ais["claude"]["logged_in"]:
        out("\nClaude Code is required (planner, builder, retro run on it). Run `claude`, log in, then `orch intro` again.")
        return None

    claude_opts = [(f"claude / {m}", m) for m in CLAUDE_MODELS]
    all_opts = [(f"claude / {m}", ("claude", m)) for m in CLAUDE_MODELS] + [(f"agy / {m}", ("agy", m)) for m in ais["agy"]["models"]]

    def default_idx(opts, cur):
        return next((i for i, (_, v) in enumerate(opts) if v == cur), 0)

    new = {"roles": {}, "reviewers": [], "agents": dict(cfg["agents"])}
    for role in ("splitter", "planner", "builder", "retro"):
        cur = cfg["roles"][role]["model"]
        m = claude_opts[default_idx(claude_opts, cur)][1] if assume_yes else _pick(f"{role}: which Claude model?", claude_opts, default_idx(claude_opts, cur), ask, out)
        new["roles"][role] = {"cli": "claude", "model": m}
    for slot, r in zip(("qa", "cross"), cfg["reviewers"], strict=False):
        cur = (r["kind"], r.get("model"))
        opts = all_opts
        i = default_idx(opts, cur)
        if slot == "cross" and cur not in [v for _, v in opts]:   # configured model not available here: prefer a non-claude one
            i = next((k for k, (_, v) in enumerate(opts) if v[0] == "agy"), 0)
        kind, model = opts[i][1] if assume_yes else _pick(f"reviewer '{slot}' (independent of the builder, should be a DIFFERENT model): which AI?", opts, i, ask, out)
        new["reviewers"].append({"name": slot, "kind": kind, "model": model, "required": True, **({"agent": "qa"} if kind == "claude" else {})})
    a, b = new["reviewers"]
    if (a["kind"], a["model"]) == (b["kind"], b["model"]):
        out("\n  note: both reviewers use the same model, cross-review is weaker.")
    agents_dir = project / ".claude" / "agents"
    have = sorted(p.stem for p in agents_dir.glob("*.md") if p.stem not in ("qa", "retro", "splitter")) if agents_dir.exists() else []
    for area in ("backend", "frontend", "both"):
        if have and not assume_yes:
            cur = cfg["agents"][area]
            new["agents"][area] = _pick(f"area '{area}': which agent implements it?", [(a, a) for a in have], have.index(cur) if cur in have else 0, ask, out)

    f = project / ".orchestrator" / "config.json"
    raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    raw.update(new)
    f.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    out("\nSaved .orchestrator/config.json. This is your pipeline:\n")
    out(tui.render(project, screen=1))
    return raw


def configured(project):
    f = Path(project) / ".orchestrator" / "config.json"
    return f.exists() and "roles" in json.loads(f.read_text(encoding="utf-8"))
