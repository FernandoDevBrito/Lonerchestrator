"""ASCII board, n8n style: pipeline nodes with sub-nodes (model/agent/memory), kanban columns, live events.
render() is a pure function of the files in the project, `loop()` just redraws it."""
import json
import shutil
import sys
import time
from pathlib import Path

from . import config
from .board import STATES, Board, Card

STAGES = ["CARD", "PLAN", "BUILD", "GUARD", "CI", "REVIEW", "MERGE"]
PHASE_IDX = {"plan": 1, "build": 2, "guardrails": 3, "ci": 4, "review": 5, "merge": 6, "retro": 6}
KIND_IDX = {"plan": 1, "build": 2, "guardrails": 3, "ci": 4, "review": 5, "card_done": 6, "retro": 6}
BAD = ("fail", "violation", "reject", "blocked", "invalid")
CODE = {"ok": "32", "running": "33", "fail": "31", "pending": "90", "info": "36"}


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


def _who(sel):
    return f"{sel.get('cli', sel.get('kind', 'claude'))[0]}:{sel.get('model') or 'default'}"


def stage_status(evs, cur):
    """status per stage for one card: running at the current phase, later stages reset, earlier ones from their last result."""
    st = ["pending"] * len(STAGES)
    st[0] = "ok"
    for e in evs:
        i = KIND_IDX.get(e["kind"])
        if i:
            res = e.get("result", "").lower()
            st[i] = "fail" if any(b in res for b in BAD) else "ok"
    if cur is not None:
        for i in range(len(STAGES)):
            st[i] = "pending" if i > cur else ("running" if i == cur else ("ok" if st[i] == "pending" else st[i]))
    return st


def reviewer_status(evs, cur, names):
    """latest verdict per reviewer for the current attempt; 'running' while review is the live phase and no verdict yet."""
    last_build = max((i for i, e in enumerate(evs) if e["kind"] == "build"), default=-1)
    got = {e["agent"]: e["result"] for e in evs[last_build + 1:] if e["kind"] == "review"}
    out = {}
    for n in names:
        v = got.get(n)
        out[n] = ("ok" if v == "APPROVED" else "fail") if v else ("running" if cur == PHASE_IDX["review"] else "pending")
    return out, got


def render(project, width=110, height=40, color=True):
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

    # ---- card facts
    card = next((Card(p) for s in STATES for p in (project / "board" / s).glob(f"{card_id}.md")), None) if card_id else None
    area = card.area if card else "backend"
    agent = cfg["agents"].get(area, "backend")
    attempt = phase.split()[1].split("/")[0] if " " in phase else (card.get("attempts", "0") if card else "0")

    # ---- header
    ai = "  ".join(f"{k}:{c('ok', 'ok') if v.get('logged_in') else c('fail', 'no')}" for k, v in ais.get("ais", {}).items()) or "run `orch intro`"
    lines = [f" ORCH  {project.name}   base: {cfg['base']}   run: {st.get('run', '-')}   AIs: {ai}",
             f" card: {c('info', card_id) if card_id else '-'}   area: {area}   phase: {phase}   attempt: {attempt}/{cfg['max_attempts']}", ""]

    # ---- nodes
    nw = 12 if width >= 108 else 10
    iw, gap = nw - 2, 4 if width >= 108 else 3
    stat = stage_status(evs, cur)
    revs, got = reviewer_status(evs, cur, [r["name"] for r in cfg["reviewers"]])
    names = ["#" + (card_id or "-").split("-")[0], "planner", "builder", "code", cfg["ci"].split()[-1].split("/")[-1], "qa+cross", "git+retro"]

    def node(i):
        s = stat[i]
        label = {"running": f"RUNNING {spin}", "ok": "ok", "fail": "FAIL", "pending": "."}[s]
        rows = ["+" + "-" * iw + "+", "|" + _cut(STAGES[i], iw).center(iw) + "|", "|" + _cut(names[i], iw).center(iw) + "|",
                "|" + _cut(label, iw).center(iw) + "|", "+" + "-" * iw + "+"]
        return [c(s, r) for r in rows]

    def sub(label, text, s):
        top = (".-" + _cut(label, iw - 2) + "-" * iw)[: iw + 1] + "."
        return [c(s, top), c(s, "|" + _cut(text, iw).center(iw) + "|"), c(s, "'" + "-" * iw + "'")]

    pl, bu, rt = cfg["roles"]["planner"], cfg["roles"]["builder"], cfg["roles"]["retro"]
    subs = {
        0: [("Input", "board/", "info")],
        1: [("Model", _who(pl), "info"), ("Memory", f"{area}.md", "info")],
        2: [("Model", _who(bu), "info"), ("Agent", agent, "info")],
        3: [("Rules", f"{len(cfg['guardrails']['protected'])} paths", "info"), ("Limit", f"{cfg['guardrails']['max_files']} files", "info")],
        4: [("Cmd", cfg["ci"].replace("bash ", ""), "info")],
        5: [(r["name"] + {"APPROVED": " OK", "REJECTED": " NO"}.get(got.get(r["name"]), ""), _who(r), revs[r["name"]]) for r in cfg["reviewers"][:2]],
        6: [("Retro", _who(rt), "info"), ("Into", cfg["base"], "info")],
    }
    nodes = [node(i) for i in range(len(STAGES))]
    for r in range(5):
        row = " "
        for i in range(len(STAGES)):
            row += nodes[i][r]
            if i < len(STAGES) - 1:
                row += c("ok" if stat[i] == "ok" else "pending", ("--->" if gap == 4 else "-->")) if r == 2 else " " * gap
        lines.append(row)
    for level in range(2):
        conn = " " + "".join((" " * (nw // 2) + c("pending", ":") + " " * (nw - nw // 2 - 1) if level < len(subs[i]) else " " * nw) + " " * gap
                             for i in range(len(STAGES)))
        lines.append(conn)
        for r in range(3):
            row = " "
            for i in range(len(STAGES)):
                row += (sub(*subs[i][level])[r] if level < len(subs[i]) else " " * nw) + " " * gap
            lines.append(row)

    # ---- kanban
    cw = max((width - 2) // len(STATES), 14)
    lines += ["", " " + "".join(f"{(s.upper() + ' (' + str(len(board.cards(s))) + ')').ljust(cw)}" for s in STATES)]
    room = max(height - len(lines) - 4, 2)
    krows = min(4, max(room // 2, 1))
    cols = {s: [x.id for x in board.cards(s)] for s in STATES}
    kind = {"backlog": "pending", "doing": "running", "review": "running", "done": "ok", "blocked": "fail"}
    for r in range(krows):
        lines.append(" " + "".join(c(kind[s], _cut(("> " if s == "doing" else "") + cols[s][r], cw - 2).ljust(cw)) if r < len(cols[s])
                                   else " " * cw for s in STATES))

    # ---- live events
    lines += ["", " LIVE"]
    n = max(height - len(lines) - 1, 1)
    for e in ev[-n:]:
        bad = any(b in (e.get("result", "") + e["kind"]).lower() for b in BAD)
        lines.append(" " + c("fail" if bad else "pending", _cut(f"{e['ts'][-8:]} {e['card'].split('-')[0]:>4} {e['agent']:<12} {e.get('result') or e['kind']}", width - 2)))
    return "\n".join(lines)


def loop(project):
    out = sys.stdout
    out.write("\x1b[?25l\x1b[2J")
    try:
        while True:
            sz = shutil.get_terminal_size((110, 40))
            frame = render(project, sz.columns, sz.lines)
            out.write("\x1b[H" + "\x1b[K\n".join(frame.splitlines()) + "\x1b[K\x1b[J")
            out.flush()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\x1b[?25h\n")
