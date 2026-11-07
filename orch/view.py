"""Simple ASCII board: six pipeline nodes (who + status), one plain-language 'NOW' line, card columns, latest events.
render() is a pure function of the files in the project; loop() just redraws it."""
import json
import shutil
import sys
import time
from pathlib import Path

from . import config
from .board import Board, Card

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


def render(project, width=110, height=30, color=True):
    project = Path(project).resolve()
    cfg = config.load(project)
    st, ev = load_events(project)
    board = Board(project)
    phase = st.get("phase") or "idle"
    card_id = st.get("card") or next((e["card"] for e in reversed(ev) if e["card"] != "-"), None)
    evs = [e for e in ev if e["card"] == card_id] if card_id else []
    cur = PHASE_IDX.get(phase.split()[0]) if st.get("card") else None
    spin = "|/-\\"[int(time.time() * 4) % 4]
    ais = _json(project / ".orchestrator" / "ais.json")

    def c(kind, text):
        return f"\x1b[{CODE[kind]}m{text}\x1b[0m" if color else text

    card = next(iter(Card(p) for s in ("backlog", "doing", "done", "blocked") for p in (project / "board" / s).glob(f"{card_id}.md")), None) if card_id else None
    ai = "  ".join(f"{k} {c('ok', 'ok') if v.get('logged_in') else c('fail', 'no')}" for k, v in ais.get("ais", {}).items()) or "run `orch intro`"
    tries = phase.split()[1].split("/")[0] if " " in phase else None
    lines = [f" ORCH  {project.name}      AIs: {ai}      base: {cfg['base']}", ""]
    lines.append(f" CARD  {c('info', card_id)}  {card.title if card else ''}" + (f"   (try {tries} of {cfg['max_attempts']})" if tries and cur is not None else "")
                 if card_id else " CARD  none yet: add one with `orch new \"title\"`")
    lines.append("")

    # ---- pipeline: who does what, and where we are
    stat = stage_status(evs, cur)
    revs, got = reviewer_status(evs, cur, [r["name"] for r in cfg["reviewers"]])
    r = cfg["roles"]
    rv = "+".join(x.get("model", "?").split("-")[0][:6] for x in cfg["reviewers"])
    who = [("splitter", r["splitter"]["model"] if cfg["split"] else "off"), ("planner", r["planner"]["model"]), ("builder", r["builder"]["model"]),
           ("rules + ci", ""), ("qa + cross", rv), ("git", cfg["base"])]
    nw = 14 if width >= 110 else 12
    iw = nw - 2
    boxes = []
    for i, name in enumerate(STAGES):
        s = stat[i]
        label = f"{spin} RUNNING" if s == "running" else WORDS[s]
        rows = ["+" + "-" * iw + "+", f"|{(str(i + 1) + ' ' + name).center(iw)}|", f"|{_cut(who[i][0], iw).center(iw)}|",
                f"|{_cut(who[i][1], iw).center(iw)}|", f"|{_cut(label, iw).center(iw)}|", "+" + "-" * iw + "+"]
        boxes.append([c(s, x) for x in rows])
    for row in range(6):
        out = " "
        for i in range(len(STAGES)):
            out += boxes[i][row]
            if i < len(STAGES) - 1:
                out += c("ok" if stat[i] == "ok" else "pending", "-->") if row == 3 else "   "
        lines.append(out)
    lines.append("")

    # ---- one plain sentence about what is happening
    if cur is None:
        blocked = board.cards("blocked")
        now = c("fail", f"NEEDS YOU: {blocked[-1].id}, answer its questions and move it back to backlog") if blocked else "idle, nothing running"
    elif cur == PHASE_IDX["review"]:
        now = "reviewing: " + ", ".join(f"{k} {'OK' if revs[k] == 'ok' else 'NO' if revs[k] == 'fail' else 'thinking'}" for k in revs)
    else:
        now = NOW.get(phase.split()[0], phase)
    lines += [f" NOW   {now}", ""]

    # ---- cards
    cols = [("TO DO", "backlog", "pending"), ("DOING", "doing", "running"), ("DONE", "done", "ok"), ("NEEDS YOU", "blocked", "fail")]
    cw = max((width - 2) // len(cols), 16)
    items = {k: [x.id for x in board.cards(k)] for _, k, _ in cols}
    lines.append(" " + "".join(f"{title} ({len(items[k])})".ljust(cw) for title, k, _ in cols))
    room = max(height - len(lines) - 6, 1)
    for n in range(min(4, room)):
        lines.append(" " + "".join(c(kind, _cut(items[k][n], cw - 2).ljust(cw)) if n < len(items[k]) else " " * cw for _, k, kind in cols))
    lines.append("")

    # ---- latest
    lines.append(" LATEST")
    for e in ev[-max(min(5, height - len(lines) - 1), 1):]:
        bad = any(b in (e.get("result", "") + e["kind"]).lower() for b in BAD)
        lines.append(" " + c("fail" if bad else "pending", _cut(f"{e['ts'][-8:-3]}  {e['card'].split('-')[0]:<4} {_sentence(e)}", width - 2)))
    return "\n".join(lines)


def loop(project):
    out = sys.stdout
    out.write("\x1b[?25l\x1b[2J")
    try:
        while True:
            sz = shutil.get_terminal_size((110, 30))
            frame = render(project, sz.columns, sz.lines)
            out.write("\x1b[H" + "\x1b[K\n".join(frame.splitlines()) + "\x1b[K\x1b[J")
            out.flush()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\x1b[?25h\n")
