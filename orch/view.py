"""Data layer for the TUI: events, stage status, reviewer verdicts, plain-language sentences."""
import json
from pathlib import Path

STAGES = ["SPLIT", "PLAN", "BUILD", "CHECKS", "REVIEW", "MERGE"]
PHASE_IDX = {"split": 0, "plan": 1, "build": 2, "guardrails": 3, "ci": 3, "review": 4, "merge": 5, "retro": 5}
KIND_IDX = {"split": 0, "plan": 1, "build": 2, "guardrails": 3, "ci": 3, "review": 4, "card_done": 5, "retro": 5}
BAD = ("fail", "violation", "reject", "blocked", "invalid")
CODE = {"ok": "32", "running": "33", "fail": "31", "pending": "90", "info": "36"}
WORDS = {"ok": "done", "running": "RUNNING", "fail": "FAILED", "pending": "waiting"}
NOW = {
    "split": "splitter is checking if the card is too big",
    "plan": "planner is writing the plan and the task list",
    "build": "builder is writing the code",
    "guardrails": "checking the rules (protected files, size, secrets)",
    "ci": "running lint, tests and build",
    "merge": "merging into the base branch",
    "retro": "retro is saving what we learned",
}


def _json(f):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_events(project):
    root = Path(project) / ".orchestrator"
    st = _json(root / "state.json")
    runs = sorted((root / "runs").glob("*")) if (root / "runs").exists() else []
    d = root / "runs" / st["run"] if st.get("run") and (root / "runs" / st["run"]).exists() else (runs[-1] if runs else None)
    ev = []
    if d and (d / "events.jsonl").exists():
        for ln in (d / "events.jsonl").read_text(encoding="utf-8").splitlines()[-500:]:
            try:
                ev.append(json.loads(ln))
            except ValueError:
                pass
    return st, ev


def _cut(s, w):
    return s if len(s) <= w else s[: max(w - 2, 1)] + ".."


def stage_status(evs, cur):
    """Running at the current phase, later stages reset to waiting, earlier ones from their last result."""
    st = ["pending"] * len(STAGES)
    for e in evs:
        i = KIND_IDX.get(e["kind"])
        if i is not None:
            res = e.get("result", "").lower()
            st[i] = "fail" if any(b in res for b in BAD) else "ok"
    if cur is not None:
        for i in range(len(STAGES)):
            st[i] = "pending" if i > cur else ("running" if i == cur else ("ok" if st[i] == "pending" else st[i]))
    return st


def reviewer_status(evs, cur, names):
    """Latest verdict per reviewer for the current attempt; 'running' while review is live and no verdict yet."""
    last_build = max((i for i, e in enumerate(evs) if e["kind"] == "build"), default=-1)
    got = {e["agent"]: e["result"] for e in evs[last_build + 1:] if e["kind"] == "review"}
    out = {}
    for n in names:
        v = got.get(n)
        out[n] = ("ok" if v == "APPROVED" else "fail") if v else ("running" if cur == PHASE_IDX["review"] else "pending")
    return out, got


def _sentence(e):
    k, r, a = e["kind"], e.get("result", ""), e["agent"]
    if k == "ci":
        return "tests " + r.split(":")[-1].strip()
    if k == "review":
        return f"{a} review: {r}"
    return f"{a}: {r or k}"
