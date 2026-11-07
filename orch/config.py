"""Per-project config: .orchestrator/config.json deep-merged over DEFAULTS."""
import copy
import json
from pathlib import Path

DEFAULTS = {
    "base": "main",                       # branch approved cards merge into
    "max_attempts": 3,                    # implement attempts per card, then blocked/
    "card_timeout_min": 45,               # wall-clock budget per card
    "ci": "bash scripts/ci.sh",           # must exit 0 to reach review
    # model per role (planner/builder/retro run through Claude Code agents; `lonerchestrator intro` sets these)
    "git_hooks": False,                   # True = run YOUR git hooks on the orchestrator's commits (an agent could plant one)
    "parallel": 1,                        # cards worked on at the same time, each in its own git worktree (1 = one after the other)
    "setup": "",                          # command run once in every new worktree before its card starts, e.g. "npm ci" (parallel only)
    "builders": 1,                        # builders working at the same time on ONE card, when its tasks declare disjoint [files: ...]
    "split": True,                        # splitter agent breaks big cards into child cards first
    "verbose": False,                     # True = full agent text in the live panes (artifacts always keep everything)
    "roles": {
        "splitter": {"cli": "claude", "model": "haiku"},
        "planner": {"cli": "claude", "model": "sonnet"},
        "builder": {"cli": "claude", "model": "sonnet"},
        "retro": {"cli": "claude", "model": "sonnet"},
        "suggester": {"cli": "claude", "model": "haiku"},      # proposes the 3 suggested answers (read-only: any AI works)
    },
    "budgets": {},                        # your own usage limits per AI: {"agy": {"tokens": 5000000, "per": "day"}} (see usage.budget_state)
    "providers": {},                      # AI CLIs you define yourself (see providers.py); they join the presets
    "agents": {"backend": "backend", "frontend": "frontend", "both": "backend"},
    # every reviewer must approve (unless required=false and its CLI is missing)
    "reviewers": [
        {"name": "qa", "kind": "claude", "agent": "qa", "model": "sonnet", "required": True},
        # works with Claude Code alone; `lonerchestrator intro` offers an Antigravity/Gemini model here for a truly different reviewer
        {"name": "cross", "kind": "claude", "agent": "qa", "model": "opus", "required": True},
    ],
    "guardrails": {
        "protected": ["scripts/**", ".claude/**", "CLAUDE.md", "GEMINI.md", ".orchestrator/**"],
        "max_files": 25,
        "max_diff_lines": 1000,
        "scan_secrets": True,
        "forbid_test_deletion": True,
    },
    "rate_limit": {"max_waits": 8, "base_seconds": 60, "cap_seconds": 1800},
}


def _merge(a, b):
    for k, v in b.items():
        a[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a


def read_raw(project) -> dict:
    f = Path(project) / ".orchestrator" / "config.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def write_raw(project, raw) -> None:
    f = Path(project) / ".orchestrator" / "config.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def load(project: Path) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    f = Path(project) / ".orchestrator" / "config.json"
    if f.exists():
        _merge(cfg, json.loads(f.read_text(encoding="utf-8")))
    return cfg
