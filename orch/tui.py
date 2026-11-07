"""Full-screen TUI, fixed size 120x34: tabs Board | Flow (n8n style) | Planner | Agents. Keyboard driven.
render() is pure (files in, string out) so every screen is testable for exact alignment."""
import os
import re
import shutil
import sys
import textwrap
import time
from pathlib import Path

from . import config, menu, term, usage
from .board import Board, Card
from .view import NOW, PHASE_IDX, _json, _sentence, load_events, reviewer_status, stage_status

W, H = 120, 34
CH = H - 5                                   # content rows: header, tabs, rule, [content], now, keys
TABS = ["Board", "Flow", "Planner", "Agents", "AIs"]
COLS = [("TO DO", "backlog", "pending"), ("DOING", "doing", "running"), ("DONE", "done", "ok"), ("NEEDS YOU", "blocked", "fail")]
CODE = {"ok": "32", "running": "33", "fail": "31", "pending": "90", "info": "36", "accent": "35", "sel": "7", "bold": "1", "text": "0"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
COLOR = True


def paint(kind, s):
    return f"\x1b[{CODE[kind]}m{s}\x1b[0m" if COLOR and s else s


def vlen(s):
    return len(ANSI.sub("", s))


def pad(s, w):
    return s + " " * (w - vlen(s))


def clip(s, w):
    return s if len(s) <= w else s[: max(w - 1, 0)] + "…"


def box(lines, w, h, title="", kind="pending", right=""):
    """Rounded box exactly w x h. Body lines may carry colors but must be <= w-2 visible."""
    t = f" {title} " if title else ""
    r = f" {right} " if right else ""
    fill = max(w - 2 - len(t) - len(r) - 1, 0)
    top = "╭─" + t + "─" * fill + r + "╮"
    top = top[: w - 1] + "╮" if len(top) > w else top
    out = [paint(kind, pad(top, w))]
    body = list(lines)[: h - 2] + [""] * max(h - 2 - len(lines), 0)
    out += [paint(kind, "│") + pad(clip_ansi(b, w - 2), w - 2) + paint(kind, "│") for b in body]
    out.append(paint(kind, "╰" + "─" * (w - 2) + "╯"))
    return out


def clip_ansi(s, w):
    return s if vlen(s) <= w else clip(ANSI.sub("", s), w)


def hcat(blocks, gap=1):
    return [(" " * gap).join(rows) for rows in zip(*blocks, strict=True)]


def fit(lines, h, w=W):
    lines = [pad(clip_ansi(ln, w), w) for ln in lines][:h]
    return lines + [" " * w] * (h - len(lines))


# --------------------------------------------------------------------------- context
class UI:
    def __init__(self):
        self.screen, self.col, self.row, self.scroll = 0, 0, 0, 0
        self.cursor, self.msg = 0, ""              # AIs tab: cursor over checklist + role rows, last action message


class Ctx:
    def __init__(self, project, ui, proc_msg=""):
        self.project = Path(project).resolve()
        self.ui, self.proc_msg = ui, proc_msg
        self.cfg = config.load(self.project)
        self.st, self.ev = load_events(self.project)
        self.board = Board(self.project)
        self.phase = self.st.get("phase") or "idle"
        self.card_id = self.st.get("card") or next((e["card"] for e in reversed(self.ev) if e["card"] != "-"), None)
        self.evs = [e for e in self.ev if e["card"] == self.card_id] if self.card_id else []
        self.cur = PHASE_IDX.get(self.phase.split()[0]) if self.st.get("card") else None
        self.stat = stage_status(self.evs, self.cur)
        self.revs, self.got = reviewer_status(self.evs, self.cur, [r["name"] for r in self.cfg["reviewers"]])
        self.spin = SPIN[int(time.time() * 8) % len(SPIN)]
        self.ais = _json(self.project / ".orchestrator" / "ais.json").get("ais", {})
        self.items = {k: self.board.cards(k) for _, k, _ in COLS}
        self.avail = menu.available(self.project)
        self.on = menu.enabled(self.project, self.avail)
        self.limits = usage.read_limits().get("claude", {})
        run_id = self.st.get("run")
        runs =sorted((self.project / ".orchestrator" / "runs").glob("*")) if (self.project / ".orchestrator" / "runs").exists() else []
        self.run_use = usage.run_totals(self.project, run_id or (runs[-1].name if runs else None))
        self.all_use = usage.all_totals(self.project)
        self.clamp()

    def clamp(self):
        u = self.ui
        u.col = min(max(u.col, 0), len(COLS) - 1)
        n = len(self.items[COLS[u.col][1]])
        u.row = min(max(u.row, 0), max(n - 1, 0))

    @property
    def selected(self):
        rows = self.items[COLS[self.ui.col][1]]
        return rows[self.ui.row] if rows else None

    def flat(self):
        return [(ci, ri) for ci, (_, k, _) in enumerate(COLS) for ri in range(len(self.items[k]))]

    def tries(self):
        return self.phase.split()[1].split("/")[0] if " " in self.phase else None

    def now(self):
        if self.cur is None:
            blocked = self.items["blocked"]
            return (paint("fail", f"NEEDS YOU: {blocked[-1].id} - answer its questions and move it back to backlog") if blocked
                    else "idle - add a card with `lonerchestrator new` and press r to run")
        if self.cur == PHASE_IDX["review"]:
            return "reviewing: " + ", ".join(f"{k} {'OK' if v == 'ok' else 'NO' if v == 'fail' else 'thinking'}" for k, v in self.revs.items())
        return NOW.get(self.phase.split()[0], self.phase) + (f" (try {self.tries()} of {self.cfg['max_attempts']})" if self.tries() else "")


# --------------------------------------------------------------------------- screens
def screen_board(x):
    widths = [30, 29, 29, 29]
    blocks = []
    for ci, (title, key, kind) in enumerate(COLS):
        w, lines = widths[ci], []
        for ri, c in enumerate(x.items[key]):
            running = c.id == x.st.get("card") and key == "doing"
            sel = ci == x.ui.col and ri == x.ui.row
            l1 = clip(("▶ " if running else "") + c.title, w - 4)
            tries = c.get("attempts", "0")
            l2 = clip(f"{c.id.split('-')[0]} · {c.area} · {tries} {'try' if tries == '1' else 'tries'}", w - 4)
            for ln, base in ((l1, "text"), (l2, "pending")):
                s = " " + pad(ln, w - 4) + " "
                lines.append(paint("sel", s) if sel else paint(base, s))
            lines.append("")
        if not lines:
            lines = [paint("pending", " (empty)")]
        count = len(x.items[key])
        blocks.append(box(lines, w, CH, title, kind, str(count)))
    return hcat(blocks)


def node(x, i, name, who, model, status):
    iw = 12
    label = f"{x.spin} RUNNING" if status == "running" else {"ok": "done", "fail": "FAILED", "pending": "waiting"}[status]
    rows = [f"{name}".center(iw), clip(who, iw).center(iw), clip(model, iw).center(iw), label.center(iw)]
    return box([paint({"pending": "pending"}.get(status, status), r) if k else paint("bold", r) for k, r in enumerate(rows)], 14, 6, kind=status)


def subnode(label, value, kind):
    return box([paint(kind if kind != "pending" else "text", clip(value, 10).center(10))], 14, 3, label, kind if kind != "pending" else "pending")


def screen_flow(x):
    r, cfg = x.cfg["roles"], x.cfg
    area = Card(next(iter(x.project.glob(f"board/*/{x.card_id}.md")))).area if x.card_id and list(x.project.glob(f"board/*/{x.card_id}.md")) else "backend"
    agent = cfg["agents"].get(area, "backend")
    st = ["ok" if x.card_id else "pending"] + x.stat
    qa_n, cross_n = [rv["name"] for rv in cfg["reviewers"]][:2]
    verdict = {"APPROVED": " OK", "REJECTED": " NO"}
    short = lambda m: (m or "-").split("-")[0]  # noqa: E731
    nodes = [("CARD", "trigger", f"#{(x.card_id or '-').split('-')[0]}"), ("1 SPLIT", "splitter", r["splitter"]["model"] if cfg["split"] else "off"),
             ("2 PLAN", "planner", r["planner"]["model"]), ("3 BUILD", "builder", r["builder"]["model"]), ("4 CHECKS", "rules + ci", ""),
             ("5 REVIEW", "qa + cross", f"{short(cfg['reviewers'][0].get('model'))}+{short(cfg['reviewers'][1].get('model'))}"), ("6 MERGE", "git", cfg["base"])]
    subs = [[("Input", "board/", "info"), ("Area", area, "info")],
            [("Model", r["splitter"]["model"], "info"), ("Rule", "3+ parts", "info")],
            [("Model", r["planner"]["model"], "info"), ("Memory", f"{area}.md", "info")],
            [("Model", r["builder"]["model"], "info"), ("Agent", agent, "info")],
            [("Rules", f"{len(cfg['guardrails']['protected'])} paths", "info"), ("CI", cfg["ci"].replace("bash ", "").split("/")[-1], "info")],
            [(qa_n + verdict.get(x.got.get(qa_n), ""), short(cfg["reviewers"][0].get("model")), x.revs[qa_n]),
             (cross_n + verdict.get(x.got.get(cross_n), ""), short(cfg["reviewers"][1].get("model")), x.revs[cross_n])],
            [("Retro", r["retro"]["model"], "info"), ("Into", cfg["base"], "info")]]
    top = hcat([node(x, i, n, w, m, st[i]) for i, (n, w, m) in enumerate(nodes)], gap=3)
    # connectors sit on the 3rd row of the node boxes
    rows = [" " * 2 + ln + " " * 2 for ln in top]
    arrow = []
    for ln_i, ln in enumerate(rows):
        if ln_i == 3:
            parts = ["  "]
            for i in range(7):
                parts.append(ln[2 + i * 17: 2 + i * 17 + 14])
                if i < 6:
                    parts.append(paint("ok" if st[i] == "ok" else "pending", "─▶ "))
            ln = "".join(parts) + "  "
        arrow.append(ln)
    drop = " " * 2 + "   ".join(" " * 6 + paint("pending", "┊") + " " * 7 for _ in range(7)) + " " * 2
    sub_rows = []
    for lvl in range(2):
        sub_rows.append(drop)
        sub_rows += [" " * 2 + "   ".join(subnode(*subs[i][lvl])[k] for i in range(7)) + " " * 2 for k in range(3)]
    flow = arrow + sub_rows                      # 6 + 8 = 14 rows
    events = []
    for e in x.ev[-(CH - len(flow) - 3):]:
        bad = any(b in (e.get("result", "") + e["kind"]).lower() for b in ("fail", "violation", "reject", "blocked", "invalid"))
        events.append(" " + paint("fail" if bad else "pending", f"{e['ts'][-8:-3]}  {e['card'].split('-')[0]:<4} {_sentence(e)}"))
    return flow + [""] + box(events, W, CH - len(flow) - 1, "LATEST", "pending", f"try {x.tries() or '-'} of {cfg['max_attempts']}")


def wrap(text, w, indent=""):
    out = []
    for para in text.splitlines():
        out += textwrap.wrap(para, w, initial_indent=indent, subsequent_indent=indent + ("  " if para.lstrip().startswith(("-", "[")) else "")) or [""]
    return out


def checklist(text, w):
    """'- [x] task' lines -> '[x] task' with a hanging indent when wrapped."""
    out = []
    for ln in text.splitlines():
        m = re.match(r"\s*- \[( |x)\] (.*)", ln)
        if not m:
            out += wrap(ln, w)
            continue
        parts = textwrap.wrap(m.group(2), w - 4) or [""]
        out.append((paint("ok", "[x]") if m.group(1) == "x" else "[ ]") + " " + parts[0])
        out += ["    " + p for p in parts[1:]]
    return out


def card_lines(card, w):
    L = []

    def head(t):
        L.extend(["", paint("accent", t.upper())])

    L.append(paint("bold", card.title) + paint("pending", f"   {card.id} · {card.area} · attempts {card.get('attempts', '0')}"))
    head("goal")
    L += wrap(card.section("Goal"), w)
    head("acceptance criteria")
    L += checklist(card.section("Acceptance criteria"), w) or [paint("pending", "-")]
    head("plan")
    L += wrap(card.section("Plan"), w) or [paint("pending", "(planner has not run yet)")]
    head("tasks")
    L += checklist(card.section("Tasks"), w) or [paint("pending", "(none yet)")]
    q = card.section("Blockers")
    if q:
        head("questions for you")
        L += [paint("fail", ln) for ln in wrap(q, w)]
    head("status log")
    L += [paint("pending", ln) for ln in wrap("\n".join(card.section("Status log").splitlines()[-6:]), w)]
    return L


def screen_planner(x):
    flat = x.flat()
    left = []
    glyph = {"backlog": ("○", "pending"), "doing": ("●", "running"), "done": ("✔", "ok"), "blocked": ("✖", "fail")}
    for ci, ri in flat:
        key = COLS[ci][1]
        c = x.items[key][ri]
        g, kind = glyph[key]
        s = f" {g} {clip(c.title, 33)}"
        sel = (ci, ri) == (x.ui.col, x.ui.row)
        left.append(paint("sel", pad(s, 38)) if sel else paint(kind, s))
    sel = x.selected
    right, title, hint = [], "no card", ""
    if sel:
        allr = card_lines(sel, 74)
        x.ui.scroll = min(max(x.ui.scroll, 0), max(len(allr) - (CH - 2), 0))
        right = [" " + ln for ln in allr[x.ui.scroll: x.ui.scroll + CH - 2]]
        title = sel.id
        hint = "PgUp/PgDn ▲▼" if len(allr) > CH - 2 else ""
    return hcat([box(left or [paint("pending", " (no cards)")], 40, CH, "CARDS", "pending", str(len(flat))), box(right, 79, CH, title, "info", hint)])


def tail_lines(path, n, w):
    try:
        data = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in data[-60:]:
        out += textwrap.wrap(ln, w, subsequent_indent="  ") or [""]
    return out[-n:]


def screen_agents(x):
    sd = x.project / ".orchestrator" / "streams"
    ph = (x.phase.split()[0] if x.cur is not None else "")
    active = {"planner": ph in ("split", "plan"), "builder": ph in ("build",), "qa": ph == "review", "cross": ph == "review", "retro": ph in ("retro",), "pipeline": x.cur is not None}
    model = {"planner": x.cfg["roles"]["planner"]["model"], "builder": x.cfg["roles"]["builder"]["model"], "retro": x.cfg["roles"]["retro"]["model"],
             "qa": x.cfg["reviewers"][0].get("model", ""), "cross": x.cfg["reviewers"][1].get("model", ""), "pipeline": "orchestrator"}
    widths, heights = [40, 39, 39], [15, 14]
    grid = [["planner", "builder", "qa"], ["cross", "retro", "pipeline"]]
    rows = []
    for ri, names in enumerate(grid):
        blocks = []
        for ci, n in enumerate(names):
            w, h = widths[ci], heights[ri]
            body = [paint("pending" if not active[n] else "text", " " + clip(ln, w - 3)) for ln in tail_lines(sd / f"{n}.log", h - 2, w - 4)]
            blocks.append(box(body, w, h, f"{n} · {clip(model[n], 14)}", "running" if active[n] and n != "pipeline" else "pending", "● live" if active[n] and n != "pipeline" else ""))
        rows += hcat(blocks)
    return rows


def fmt_n(n):
    return str(n) if n < 1000 else f"{n / 1000:.1f}k" if n < 1_000_000 else f"{n / 1_000_000:.1f}M"


def fmt_eta(secs):
    secs = int(secs)
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return f"{d}d {h}h" if d else f"{h}h {m:02d}m" if h else f"{m}m"


def bar(frac, width=18):
    frac = min(max(frac, 0.0), 1.0)
    full = round(frac * width)
    kind = "ok" if frac < 0.6 else "running" if frac < 0.85 else "fail"
    return paint(kind, "█" * full) + paint("pending", "░" * (width - full))


def window_line(label, w, now):
    """One account-limit window of Claude Code, e.g. the 5-hour session."""
    if not w or w.get("utilization") is None:
        return f" {label:<15}" + paint("pending", "no data yet")
    reset = w.get("resetsAt") or 0
    if reset and reset < now:
        return f" {label:<15}" + paint("pending", "window reset since - press u to refresh")
    frac = w["utilization"]
    when = f"resets in {fmt_eta(reset - now)}" if reset else ""
    return f" {label:<15}{bar(frac)} {round(frac * 100):>3}%  {paint('pending', when)}"


def usage_table(title, data, ai):
    rows = data.get(ai, {})
    if not rows:
        return [paint("pending", f" {title:<14}no calls yet")]
    out = [paint("pending", f" {title:<12}{'calls':>6}{'tokens in':>11}{'out':>8}")]
    for model, m in sorted(rows.items()):
        out.append(f" {clip(model, 12):<12}{m['calls']:>6}{fmt_n(m['in']):>11}{fmt_n(m['out']):>8}")
    return out


def usage_summary(x):
    """Compact one-liner for the header: Claude's account windows and agy's token count."""
    now = time.time()
    w = x.limits.get("windows", {})
    parts = []
    for key, label in (("five_hour", "5h"), ("seven_day", "wk")):
        win = w.get(key)
        if win and win.get("utilization") is not None and not (win.get("resetsAt") and win["resetsAt"] < now):
            f = win["utilization"]
            parts.append(label + " " + paint("ok" if f < 0.6 else "running" if f < 0.85 else "fail", f"{round(f * 100)}%"))
    claude = " ".join(parts) or paint("pending", "limits ?")
    agy_tok = sum(m["in"] + m["out"] for m in x.all_use.get("agy", {}).values())
    return claude, (f"{fmt_n(agy_tok)} tok" if agy_tok else "")


def ai_rows(x):
    """Checklist rows: ('head', text) or ('item', key). Items are the selectable AI models."""
    rows = []
    for cli, label in (("claude", "Claude Code"), ("agy", "Antigravity (agy)")):
        info = x.ais.get(cli, {})
        state = "logged in" if info.get("logged_in") else ("installed, NOT logged in" if info.get("installed") else "not installed")
        rows.append(("head", f"{label}  -  {state}" if info else f"{label}  -  not detected yet (press d)"))
        rows += [("item", menu.keyof(c, m)) for c, m in x.avail if c == cli]
    return rows


def screen_ais(x):
    rows = ai_rows(x)
    items = [r[1] for r in rows if r[0] == "item"]
    total = len(items) + len(menu.SLOTS)
    x.ui.cursor = min(max(x.ui.cursor, 0), max(total - 1, 0))
    cur = x.ui.cursor
    used = {}
    for s in menu.SLOTS:
        used.setdefault(menu.assigned(x.cfg, s), []).append(s)
    # --- checklist
    lines, sel_line = [], 0
    for kind, v in rows:
        if kind == "head":
            lines.append(paint("bold", " " + clip(v, 54)))
            continue
        idx = items.index(v)
        mark = paint("ok", "[x]") if v in x.on else "[ ]"
        tag = clip(", ".join(used.get(v, [])), 20)
        s = f" {mark} {clip(v.split('/', 1)[1], 30):<31}" + paint("info", tag)
        if idx == cur:
            sel_line = len(lines)
            s = paint("sel", pad(ANSI.sub("", s), 56))
        lines.append(s)
    room = 15
    start = min(max(sel_line - room // 2, 0), max(len(lines) - room, 0))
    shown = lines[start:start + room] or [paint("pending", " (no AI detected: press d)")]
    left_top = box(shown, 58, 17, "AIs TO USE  (space = check)", "info", f"{len(x.on)} on")
    # --- who does what
    role_lines = []
    for i, slot in enumerate(menu.SLOTS):
        key = menu.assigned(x.cfg, slot)
        ok = key in x.on or x.cfg.get("use") is None
        s = f" {slot:<9}◂ {clip(key, 36):<36} ▸" + ("" if ok else " !")
        role_lines.append(paint("sel", pad(s, 56)) if len(items) + i == cur else (s if ok else paint("fail", s)))
        if slot == "retro":
            role_lines.append(paint("pending", " reviewers:"))
    same = menu.assigned(x.cfg, "qa") == menu.assigned(x.cfg, "cross")
    role_lines += ["", paint("running", " ! qa and cross use the same model") if same else paint("pending", " qa and cross are different models: good")]
    left_bot = box(role_lines, 58, 12, "WHO DOES WHAT  (←/→ change)", "info")
    # --- usage
    now = time.time()
    w = x.limits.get("windows", {})
    upd = x.limits.get("updated")
    ago = f"updated {fmt_eta(now - upd)} ago" if upd else "never read"
    u = [paint("bold", " CLAUDE CODE") + paint("pending", f" · your account limits · {ago}"),
         window_line("5-hour session", w.get("five_hour"), now), window_line("weekly", w.get("seven_day"), now)]
    if x.limits.get("status") not in (None, "allowed", "allowed_warning"):
        u.append(paint("fail", f" status: {x.limits.get('status')}"))
    u += [""] + usage_table("this run", x.run_use, "claude") + usage_table("all runs", x.all_use, "claude")
    u += ["", paint("bold", " ANTIGRAVITY (agy)"), paint("pending", " account quota: not exposed by agy (tokens only)")]
    u += usage_table("this run", x.run_use, "agy") + usage_table("all runs", x.all_use, "agy")
    probe = usage.PROBE
    note = probe["msg"] if probe["msg"] else ""
    u += ["", paint("pending", " u refresh limits (1 tiny haiku call)    d re-detect AIs"), " " + paint("info", ("⠿ " if probe["running"] else "") + (x.ui.msg or note))]
    right = box(u, 61, 29, "USAGE · live", "ok" if x.limits else "pending")
    return [f"{a} {b}" for a, b in zip(left_top + left_bot, right, strict=True)]


def handle_ais(key, ui, x):
    """Keys of the AIs tab. True when the key was consumed."""
    items = [r[1] for r in ai_rows(x) if r[0] == "item"]
    total = len(items) + len(menu.SLOTS)
    if key in ("up", "down"):
        ui.cursor = (ui.cursor + (-1 if key == "up" else 1)) % max(total, 1)
    elif key in (" ", "\r", "\n"):
        ui.msg = menu.toggle(x.project, items[ui.cursor]) if ui.cursor < len(items) else menu.cycle(x.project, menu.SLOTS[ui.cursor - len(items)], 1)
    elif key in ("left", "right") and ui.cursor >= len(items):
        ui.msg = menu.cycle(x.project, menu.SLOTS[ui.cursor - len(items)], -1 if key == "left" else 1)
    elif key == "u":
        usage.probe_in_background(x.project)
        ui.msg = "asking Claude Code for your current limits..."
    elif key == "d":
        import threading

        from . import intro
        threading.Thread(target=lambda: intro.save_ais(x.project, intro.detect()), daemon=True).start()
        ui.msg = "detecting logged-in AIs (a few seconds)..."
    else:
        return False
    return True


SCREENS = [screen_board, screen_flow, screen_planner, screen_agents, screen_ais]


# --------------------------------------------------------------------------- frame
def frame(x):
    cfg = x.cfg
    claude_use, agy_use = usage_summary(x)
    extra = {"claude": claude_use, "agy": agy_use}
    ai = "   ".join(f"{k} {paint('ok', '●') if v.get('logged_in') else paint('fail', '●')} {extra.get(k, '')}".rstrip() for k, v in x.ais.items()) \
        or "run `lonerchestrator intro`"
    left = f" ORCH ▸ {x.project.name}"
    right = f"base {cfg['base']}   {ai} "
    head = left + " " * (W - len(left) - vlen(right)) + right
    tabs = " ".join(paint("sel", f" {i + 1} {n} ") if i == x.ui.screen else paint("pending", f" {i + 1} {n} ") for i, n in enumerate(TABS))
    run = x.proc_msg or (paint("running", f"{x.spin} pipeline running") if x.cur is not None else paint("pending", "idle"))
    tabs_line = tabs + " " * (W - vlen(tabs) - vlen(run) - 1) + run + " "
    keys = (" ↑↓ move   space check / change   ←→ change model   u refresh limits   d detect AIs   1-5 views   q quit" if x.ui.screen == 4
            else " ←→↑↓ move   1-5 / Tab views   r run   x stop   PgUp/PgDn scroll   q quit")
    body = fit(SCREENS[x.ui.screen](x), CH)
    return [pad(head, W), pad(tabs_line, W), paint("pending", "─" * W)] + body + [pad(" NOW  " + x.now(), W), paint("pending", pad(keys, W))]


def render(project, screen=0, ui=None, color=True, proc_msg=""):
    """Whole screen as a string: exactly H lines, each exactly W visible columns."""
    global COLOR
    COLOR = color
    ui = ui or UI()
    ui.screen = screen
    return "\n".join(frame(Ctx(project, ui, proc_msg)))


# --------------------------------------------------------------------------- interactive loop
class Runner:
    """Starts/stops the pipeline as a background process owned by the TUI."""

    def __init__(self, project, base):
        self.project, self.base, self.proc = project, base, None
        self.msg = ""

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        root = Path(__file__).resolve().parent.parent
        d = self.project / ".orchestrator"
        d.mkdir(exist_ok=True)
        env = {**os.environ, "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""), "PYTHONIOENCODING": "utf-8"}
        out = open(d / "run.out", "w", encoding="utf-8")  # noqa: SIM115
        self.proc = term.spawn([sys.executable, "-m", "orch", "-C", str(self.project), "run", "--base", self.base], self.project, env, out)

    def stop(self):
        if self.proc:
            term.kill_tree(self.proc)

    def status(self):
        if not self.proc:
            return ""
        rc = self.proc.poll()
        if rc is None:
            return paint("running", f"{SPIN[int(time.time() * 8) % 10]} run in progress")
        if rc == 0:
            return paint("ok", "run finished")
        tail = (self.project / ".orchestrator" / "run.out").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:]
        return paint("fail", clip(f"run stopped (rc {rc}): {tail[0] if tail else ''}", 60))


def handle(key, ui, x, runner):
    n = len(COLS)
    if key and key in "12345":
        ui.screen, ui.scroll = int(key) - 1, 0
    elif key == "\t":
        ui.screen, ui.scroll = (ui.screen + 1) % len(TABS), 0
    elif ui.screen == 4 and handle_ais(key, ui, x):
        pass
    elif key == "left" and ui.screen == 0:
        ui.col, ui.row = (ui.col - 1) % n, ui.row
    elif key == "right" and ui.screen == 0:
        ui.col, ui.row = (ui.col + 1) % n, ui.row
    elif key in ("up", "down"):
        d = -1 if key == "up" else 1
        if ui.screen == 2:                     # planner: move through the flat list
            fl = x.flat()
            if fl and (ui.col, ui.row) in fl:
                ui.col, ui.row = fl[(fl.index((ui.col, ui.row)) + d) % len(fl)]
                ui.scroll = 0
        else:
            ui.row += d
    elif key == "pgup":
        ui.scroll -= CH - 4
    elif key == "pgdn":
        ui.scroll += CH - 4
    elif key == "r":
        runner.start()
    elif key == "x":
        runner.stop()


def fit_window(out):
    """Ask terminals that support it (xterm, macOS Terminal, ...) to resize to W x H. Others ignore the sequence."""
    sz = shutil.get_terminal_size((W, H))
    if sz.columns < W or sz.lines < H:
        out.write(f"\x1b[8;{max(sz.lines, H)};{max(sz.columns, W)}t")
        out.flush()
        time.sleep(0.3)


def run_tui(project, base, autorun=False, tab=1):
    global COLOR
    COLOR = True
    project = Path(project).resolve()
    out, ui, runner = sys.stdout, UI(), Runner(project, base)
    ui.screen = min(max(tab, 1), len(TABS)) - 1
    (project / ".orchestrator").mkdir(exist_ok=True)
    fit_window(out)
    out.write("\x1b[?1049h\x1b[?25l")
    if autorun:
        runner.start()
    last_size = None
    try:
        with term.RawTerminal():
            while True:
                sz = shutil.get_terminal_size((W, H))
                (project / ".orchestrator" / "tui.size").write_text(f"{sz.columns}x{sz.lines}", encoding="utf-8")
                x = Ctx(project, ui, runner.status())
                for k in term.read_keys():
                    if k in ("q", ""):
                        return
                    handle(k, ui, x, runner)
                    x = Ctx(project, ui, runner.status())
                if sz != last_size:
                    out.write("\x1b[2J")
                    last_size = sz
                if sz.columns < W or sz.lines < H:
                    msg = f"Window too small: need {W}x{H}, have {sz.columns}x{sz.lines}. Enlarge it (or run `lonerchestrator live`)."
                    out.write("\x1b[H" + msg + "\x1b[K")
                else:
                    ox, oy = (sz.columns - W) // 2, (sz.lines - H) // 2
                    out.write("\x1b[H" + "\n" * oy + "\n".join(" " * ox + ln for ln in frame(x)))
                out.flush()
                time.sleep(0.12)
    except KeyboardInterrupt:
        pass
    finally:
        out.write("\x1b[?25h\x1b[?1049l")
        if runner.proc and runner.proc.poll() is None:
            print("pipeline is still running in the background (`lonerchestrator status`, or open the panel again)")
