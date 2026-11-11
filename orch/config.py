"""Per-project config: config.json in the project's folder (folder.py) deep-merged over DEFAULTS."""
import copy
import json

from . import folder

DEFAULTS = {
    "base": "main",                       # branch approved cards merge into
    "max_attempts": 3,                    # implement attempts per card, then blocked/
    "card_timeout_min": 45,               # wall-clock budget per card
    "ci": 'bash "{folder}/ci.sh"',        # must exit 0 to reach review; runs in the project; {folder} = the project's folder (folder.py)
    # model per role (planner/builder/retro run through Claude Code agents; `lonerchestrator intro` sets these)
    "git_hooks": False,                   # True = run YOUR git hooks on the orchestrator's commits (an agent could plant one)
    "parallel": 1,                        # cards worked on at the same time, each in its own git worktree (1 = one after the other)
    "setup": "",                          # command run once in every new worktree before its card starts, e.g. "npm ci" (parallel only)
    "builders": 1,                        # builders working at the same time on ONE card, when its tasks declare disjoint [files: ...]
    "split": True,                        # splitter agent breaks big cards into child cards first
    "verbose": False,                     # True = full agent text in the live panes (artifacts always keep everything)
    # each role (and reviewer) may add "effort": "low" | "medium" | "high" | "xhigh" | "max" (how hard the model thinks; unset = the CLI's default)
    "roles": {
        "splitter": {"cli": "claude", "model": "haiku"},
        "planner": {"cli": "claude", "model": "sonnet"},
        "builder": {"cli": "claude", "model": "sonnet"},
        "retro": {"cli": "claude", "model": "sonnet"},
        "suggester": {"cli": "claude", "model": "haiku"},      # proposes the 3 suggested answers (read-only: any AI works)
    },
    "budgets": {},                        # your own usage limits per AI: {"agy": {"tokens": 5000000, "per": "day"}} (see usage.budget_state)
    "providers": {},                      # AI CLIs you define yourself (see providers.py); they join the presets
    # area -> agent (agents/<agent>.md in the project's folder). The keys are the areas a card may have: add your own ("data": "data-eng") and write that agent
    "agents": {"backend": "backend", "frontend": "frontend", "both": "backend", "docs": "docs"},
    # every reviewer must approve (unless required=false and its CLI is missing)
    "reviewers": [
        {"name": "qa", "kind": "claude", "agent": "qa", "model": "sonnet", "required": True},
        # works with Claude Code alone; `lonerchestrator intro` offers an Antigravity/Gemini model here for a truly different reviewer
        {"name": "cross", "kind": "claude", "agent": "qa", "model": "opus", "required": True},
    ],
    "guardrails": {
        "protected": [".claude/**", "CLAUDE.md", "GEMINI.md"],      # your AI tools' own setup in the project: agents never change it
        "max_files": 25,
        "max_diff_lines": 1000,
        "scan_secrets": True,
        "forbid_test_deletion": True,
    },
    "rate_limit": {"max_waits": 8, "base_seconds": 60, "cap_seconds": 1800},
    # change graph of every attempt (graph.py): a view of the diff, it never approves or blocks anything
    "graph": {"enabled": True, "review_summary": False},     # review_summary = reviewers also read a short graph summary
}


def areas(cfg):
    """The areas a card may have: the keys of the `agents` map."""
    return tuple(cfg["agents"])


def _merge(a, b):
    for k, v in b.items():
        a[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a


def read_raw(project) -> dict:
    f = folder.of(project) / "config.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def write_raw(project, raw) -> None:
    f = folder.of(project) / "config.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def merged(raw) -> dict:
    """DEFAULTS with `raw` (what a config.json holds) on top."""
    return _merge(copy.deepcopy(DEFAULTS), raw)


def load(project) -> dict:
    return merged(read_raw(project))
