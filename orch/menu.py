"""The AIs menu: which AIs/models this project may use (checklist) and who does what. Pure logic, the TUI only draws it.

Keys are "cli/model", e.g. "claude/sonnet" or "agy/gemini-4-argon-high".
Everything is saved to .orchestrator/config.json on every change, so there is no separate "save" step."""
import json
from pathlib import Path

from . import config

CLAUDE_MODELS = ["sonnet", "opus", "haiku"]
ROLES = ["splitter", "planner", "builder", "retro"]        # run on Claude Code agents
REVIEWERS = ["qa", "cross"]                                 # any enabled AI
SLOTS = ROLES + REVIEWERS


def available(project):
    """[(cli, model)] for the AIs detected as logged in (from .orchestrator/ais.json, written by the introduction)."""
    f = Path(project) / ".orchestrator" / "ais.json"
    try:
        ais = json.loads(f.read_text(encoding="utf-8")).get("ais", {})
    except (OSError, ValueError):
        ais = {}
    return [(cli, m) for cli in ("claude", "agy") if ais.get(cli, {}).get("logged_in") for m in ais[cli].get("models", [])]


def keyof(cli, model):
    return f"{cli}/{model}"


def enabled(project, avail=None):
    """Enabled keys, in display order. Default (nothing saved yet): every available Claude model."""
    avail = available(project) if avail is None else avail
    use = config.read_raw(project).get("use")
    if use is None:
        use = [keyof(c, m) for c, m in avail if c == "claude"]
    return [keyof(c, m) for c, m in avail if keyof(c, m) in use]


def assigned(cfg, slot):
    """Current 'cli/model' key of a role/reviewer slot."""
    if slot in ROLES:
        r = cfg["roles"][slot]
        return keyof(r.get("cli", "claude"), r.get("model"))
    r = next(x for x in cfg["reviewers"] if x["name"] == slot)
    return keyof(r["kind"], r.get("model"))


def _assign(raw, cfg, slot, key):
    cli, model = key.split("/", 1)
    if slot in ROLES:
        raw.setdefault("roles", {})[slot] = {"cli": "claude", "model": model}
    else:
        revs = raw.get("reviewers") or json.loads(json.dumps(cfg["reviewers"]))
        for r in revs:
            if r["name"] == slot:
                r.clear()
                r.update({"name": slot, "kind": cli, "model": model, "required": True, **({"agent": "qa"} if cli == "claude" else {})})
        raw["reviewers"] = revs


def toggle(project, key):
    """Check/uncheck one AI model. Slots that used an unchecked model are moved to another enabled one. Returns a message."""
    avail = available(project)
    on = enabled(project, avail)
    raw, cfg = config.read_raw(project), config.load(Path(project))
    if key in on:
        left = [k for k in on if k != key]
        if not any(k.startswith("claude/") for k in left):
            return "Keep at least one Claude model checked: planner, builder and retro run on Claude Code."
        for slot in SLOTS:
            if assigned(cfg, slot) == key:
                pool = [k for k in left if slot in REVIEWERS or k.startswith("claude/")]
                _assign(raw, cfg, slot, pool[0])
        on = left
        msg = f"{key} unchecked"
    else:
        on = [k for k in (keyof(c, m) for c, m in avail) if k in on or k == key]
        msg = f"{key} checked"
    raw["use"] = on
    config.write_raw(project, raw)
    return msg


def options(project, slot):
    on = enabled(project)
    return [k for k in on if slot in REVIEWERS or k.startswith("claude/")]


def cycle(project, slot, delta):
    """Give a slot the next/previous enabled model. Returns a message."""
    opts = options(project, slot)
    if not opts:
        return "No model enabled for this slot: check one above."
    raw, cfg = config.read_raw(project), config.load(Path(project))
    cur = assigned(cfg, slot)
    key = opts[(opts.index(cur) + delta) % len(opts)] if cur in opts else opts[0]
    _assign(raw, cfg, slot, key)
    config.write_raw(project, raw)
    return f"{slot} -> {key}"


def problems(cfg):
    """Slots using a model that is not enabled (only checked once the user has used the menu: cfg['use'] exists)."""
    use = cfg.get("use")
    if use is None:
        return []
    return [f"{slot} uses {assigned(cfg, slot)}, which is not checked in the AIs menu" for slot in SLOTS if assigned(cfg, slot) not in use]
