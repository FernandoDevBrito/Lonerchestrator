"""Project settings editable from the panel (Settings tab). Pure logic: the TUI only draws it.
Every change is saved to .orchestrator/config.json at once, so there is no separate "save" step."""
from pathlib import Path

from . import config, trust
from .gitops import Git
from .safe import clean

# (key, label, kind, options, unit, help)
SPEC = [
    ("base", "Base branch", "branch", None, "",
     "Approved cards are merged into this branch. Pick a scratch branch to keep main untouched until you review."),
    ("ci", "CI command", "text", None, "",
     "Runs through a shell after every build: lint, tests, build. It must exit 0. Enter edits it; the command you type is approved."),
    ("max_attempts", "Attempts per card", "choice", [1, 2, 3, 4, 5], "",
     "How many times the builder may retry after a rejection before the card is parked for you."),
    ("parallel", "Cards at the same time", "choice", [1, 2, 3, 4], "",
     "How many cards are worked on together, each in its own git worktree. 1 = one after the other. Cards that depend on each other need `depends:` in the card."),
    ("split", "Split big cards", "bool", None, "",
     "A splitter agent breaks cards with 3+ independent deliverables into small cards. Costs one cheap call per card."),
    ("card_timeout_min", "Time limit per card", "choice", [15, 30, 45, 90, 180], " min",
     "A card that takes longer is parked, so a stuck agent cannot run forever."),
    ("guardrails.max_files", "Max files per card", "choice", [10, 25, 50, 100], "",
     "A change touching more files is sent back to the builder: split the card instead."),
    ("guardrails.max_diff_lines", "Max changed lines", "choice", [300, 1000, 3000], "",
     "Same limit, counted in changed lines."),
    ("verbose", "Full agent text in panes", "bool", None, "",
     "Off shows only tool actions and the result line. The full text is always saved in the run folder."),
    ("git_hooks", "Run my git hooks", "bool", None, "",
     "On: your git hooks run on the orchestrator's commits. Off is safer: an agent could plant a hook."),
]
KEYS = [s[0] for s in SPEC]


def spec(key):
    return next(s for s in SPEC if s[0] == key)


def _get(d, key):
    for part in key.split("."):
        d = d[part]
    return d


def _put(raw, key, value):
    d = raw
    parts = key.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


def get(cfg, key):
    return _get(cfg, key)


def value(project, key):
    return _get(config.load(Path(project)), key)


def show(val, key):
    """How a value is displayed in the list."""
    s = spec(key)
    if s[2] == "bool":
        return "on" if val else "off"
    return f"{val}{s[4]}"


def branches(project):
    """Local branches the user can merge into (card/* work branches are not offered)."""
    try:
        names = Git(project).out("for-each-ref", "--format=%(refname:short)", "refs/heads").split()
    except RuntimeError:
        return []
    return [b for b in names if not b.startswith("card/")]


def change(project, key, delta=1):
    """Toggle a bool, or move a choice/branch to the next/previous option. Returns a message for the status line."""
    label, kind, options = spec(key)[1], spec(key)[2], spec(key)[3]
    if kind == "text":
        return "press Enter to edit this one"
    cur = value(project, key)
    if kind == "bool":
        new = not cur
    else:
        opts = branches(project) if kind == "branch" else options
        if not opts:
            return "no branches found: make a first commit"
        new = opts[(opts.index(cur) + delta) % len(opts)] if cur in opts else opts[0]
    raw = config.read_raw(project)
    _put(raw, key, new)
    config.write_raw(project, raw)
    return f"{label}: {show(new, key)}"


def set_text(project, key, text):
    """Save a free-text setting (only the CI command). Typing the command here is the approval, so it is trusted right away."""
    text = " ".join(clean(text).split())
    if key == "ci" and not 0 < len(text) <= 300:
        return "the CI command must be 1 to 300 characters"
    raw = config.read_raw(project)
    _put(raw, key, text)
    config.write_raw(project, raw)
    if key == "ci":
        cfg = config.load(Path(project))
        if cfg.get("providers") and not trust.is_trusted(project, cfg):
            return "CI command saved. This project also defines AI commands: read them and run `lonerchestrator trust`"   # typing a CI command must not approve them
        trust.trust(project, cfg)
        return "CI command saved and approved"
    return f"{spec(key)[1]} saved"
