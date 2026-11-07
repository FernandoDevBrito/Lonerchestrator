"""Per-project config: .orchestrator/config.json deep-merged over DEFAULTS."""
import copy
import json
from pathlib import Path

DEFAULTS = {
    "base": "main",                       # branch approved cards merge into
    "max_attempts": 3,                    # implement attempts per card, then blocked/
    "card_timeout_min": 45,               # wall-clock budget per card
    "ci": "bash scripts/ci.sh",           # must exit 0 to reach review
    "agents": {"backend": "backend", "frontend": "frontend", "both": "backend"},
    # every reviewer must approve (unless required=false and its CLI is missing)
    "reviewers": [
        {"name": "qa", "kind": "claude", "agent": "qa", "required": True},
        {"name": "gemini", "kind": "agy", "model": "gemini-4-argon-high", "required": True},
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


def load(project: Path) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    f = Path(project) / ".orchestrator" / "config.json"
    if f.exists():
        _merge(cfg, json.loads(f.read_text(encoding="utf-8")))
    return cfg
