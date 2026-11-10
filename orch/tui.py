"""Full-screen panel, fixed size 120x34. Tabs: Board | Flow | Planner | Agents | AIs. Keyboard driven.
render() is pure (files in, string out) so every screen is testable for exact alignment.
Look: 256-color theme, almost no borders, one-line cards, glyphs instead of words."""
import os
import re
import shutil
import sys
import textwrap
import time
from pathlib import Path

from . import answer, checks, config, menu, providers, settings, term, usage
from .board import Board, Card, create_card
from .safe import clean, keep_sgr
from .view import PHASE_IDX, _json, load_events, reviewer_status, stage_status

W, H = 120, 34
CH = H - 5                                   # content rows: header, tabs, rule, [content], now, keys
TABS = ["Board", "Flow", "Planner", "Agents", "AIs", "Settings"]
COLS = [("To do", "backlog", "dim"), ("Doing", "doing", "running"), ("Done", "done", "ok"), ("Needs you", "blocked", "fail")]
CODE = {"text": "38;5;252", "bold": "1;38;5;255", "dim": "38;5;243", "faint": "38;5;239", "pending": "38;5;243",
        "ok": "38;5;78", "running": "38;5;214", "fail": "38;5;203", "info": "38;5;110", "accent": "1;38;5;80",
        "sel": "48;5;237;38;5;255", "tab": "1;38;5;80;48;5;236"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
GLYPH = {"ok": "✓", "fail": "×", "pending": "○"}
SHORT = {"split": "splitting the card", "plan": "planning", "build": "building", "guardrails": "checking the rules", "ci": "running tests",
         "merge": "merging", "retro": "saving lessons"}
COLOR = True


# --------------------------------------------------------------------------- drawing helpers
def paint(kind, s):
    return f"\x1b[{CODE[kind]}m{s}\x1b[0m" if COLOR and s else s


def vlen(s):
    return len(ANSI.sub("", s))


def pad(s, w):
    return s + " " * (w - vlen(s))


def center(s, w):
    gap = max(w - vlen(s), 0)
    return " " * (gap // 2) + s + " " * (gap - gap // 2)


def clip(s, w):
    s = clean(s)
    return s if len(s) <= w else s[: max(w - 1, 0)] + "…"


def clip_ansi(s, w):
    return s if vlen(s) <= w else clip(ANSI.sub("", s), w)


def rule(w, title="", kind="faint", tkind="accent"):
    if not title:
        return paint(kind, "─" * w)
    t = f" {clip(title, w - 6)} "
    return paint(kind, "──") + paint(tkind, t) + paint(kind, "─" * max(w - 2 - len(t), 0))


def box(lines, w, h, title="", kind="faint", right="", tkind="bold"):
    """Rounded box exactly w x h. Body lines may carry colors but must be <= w-2 visible."""
    t = f" {title} " if title else ""
    r = f" {right} " if right else ""
    if w - 3 - len(t) - len(r) < 0:
        t, r = clip(t, max(w - 4, 0)), ""
    fill = max(w - 3 - len(t) - len(r), 0)
    out = [paint(kind, "╭─") + paint(tkind, t) + paint(kind, "─" * fill) + paint("dim", r) + paint(kind, "╮")]
    body = list(lines)[: h - 2] + [""] * max(h - 2 - len(lines), 0)
    out += [paint(kind, "│") + pad(clip_ansi(b, w - 2), w - 2) + paint(kind, "│") for b in body]
    out.append(paint(kind, "╰" + "─" * (w - 2) + "╯"))
    return out


def hcat(blocks, gap=1):
    return [(" " * gap).join(rows) for rows in zip(*blocks, strict=True)]


def fit(lines, h, w=W):
    lines = [pad(clip_ansi(ln, w), w) for ln in lines][:h]
    return lines + [" " * w] * (h - len(lines))


def selrow(text, w):
    """Highlighted row: strip inner colors so the background is continuous."""
    return paint("sel", pad(clip(ANSI.sub("", text), w), w))


# --------------------------------------------------------------------------- context
class UI:
    def __init__(self):
        self.screen, self.col, self.row, self.scroll = 0, 0, 0, 0
        self.cursor, self.msg = 0, ""              # AIs tab: cursor over checklist + role rows, last action message
        self.scur, self.edit_key, self.checks, self.checks_t = 0, "", [], 0.0      # Settings tab: cursor, field being edited, cached readiness
        self.mode, self.qcard, self.qs, self.ans, self.buf = None, "", [], [], ""      # answering a blocked card's questions
        self.qopts = []                                                                  # the suggested answers of each question
        self.area = "backend"                                                            # the "new request" box: which agent builds it
        self.suggesting = False                                                          # fetching suggestions for questions that came without


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
        runs_dir = self.project / ".orchestrator" / "runs"
        runs = sorted(runs_dir.glob("*")) if runs_dir.exists() else []
        self.run_use = usage.run_totals(self.project, self.st.get("run") or (runs[-1].name if runs else None))
        self.all_use = usage.all_totals(self.project)
        self.budgets = usage.budget_state(self.cfg, self.project)
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
        return int(self.phase.split()[1].split("/")[0]) if " " in self.phase else None

    def glyph(self, status):
        return self.spin if status == "running" else GLYPH[status]

    def now(self):
        if self.ui.mode == "answer":
            return paint("info", f"\u25b8 answering {self.ui.qcard.split('-')[0]}") + paint("dim", f" \u00b7 question {len(self.ui.ans) + 1} of {len(self.ui.qs)}")
        if self.ui.mode == "edit":
            return paint("info", f"\u25b8 editing {settings.spec(self.ui.edit_key)[1]}")
        if self.ui.msg and self.ui.screen in (0, 2, 5):
            return paint("ok", "\u25b8 " + self.ui.msg)
        if self.cur is None:
            blocked = self.items["blocked"]
            if blocked:
                return paint("fail", f"▸ {blocked[-1].id.split('-')[0]} needs you") + paint("dim", " · press a to answer its questions")
            return paint("dim", "▸ idle · press r to run the backlog")
        if self.cur == PHASE_IDX["review"]:
            g = {"ok": paint("ok", "✓"), "fail": paint("fail", "×"), "running": paint("running", self.spin), "pending": "·"}
            return "▸ reviewing · " + "  ".join(f"{k} {g[v]}" for k, v in self.revs.items())
        t = f" · try {self.tries()}/{self.cfg['max_attempts']}" if self.tries() else ""
        return paint("running", f"▸ {SHORT.get(self.phase.split()[0], self.phase)}") + paint("dim", t)


def event_line(e, w):
    bad = any(b in (e.get("result", "") + e["kind"]).lower() for b in ("fail", "violation", "reject", "blocked", "invalid"))
    k, r, a = e["kind"], e.get("result", ""), e["agent"]
    text = ("tests " + r.split(":")[-1].strip().lower()) if k == "ci" else (f"{a} {r.lower()}" if k == "review" else (f"{a} {r or k}" if a != "-" else (r or k)))
    dot = paint("fail", "×") if bad else paint("ok", "✓") if any(w_ in text for w_ in ("pass", "approved", "done", "planned", "merged", "ok")) else paint("dim", "•")
    return " " + paint("dim", f"{e['ts'][-8:-3]}  {e['card'].split('-')[0]:<4}") + f" {dot} " + paint("text", clip(text, w - 16))


# --------------------------------------------------------------------------- screens
def screen_board(x):
    widths, gap, margin = [27, 27, 27, 26], 3, 2
    blocks = []
    for ci, (title, key, kind) in enumerate(COLS):
        w, rows = widths[ci], []
        n = len(x.items[key])
        rows.append(paint(kind if kind != "dim" else "text", "● ") + paint("bold", title) + paint("dim", f"  {n}"))
        rows.append(paint(kind if kind != "dim" else "faint", "━" * w))
        for ri, c in enumerate(x.items[key]):
            running = key == "doing" and (c.id == x.st.get("card") or c.id in (x.st.get("active") or {}))
            tries = int(c.get("attempts", "0") or 0)
            ident = c.id.split("-")[0] + (f" ({tries})" if tries > 1 else "")
            mark = x.spin if running else "▎"
            title_c = clip(c.title, w - len(ident) - 4)
            if ci == x.ui.col and ri == x.ui.row:
                rows.append(selrow(pad(f"{mark} {title_c}", w - len(ident) - 1) + " " + ident, w))
            else:
                colored = paint("running" if running else (kind if kind != "dim" else "faint"), mark) + " " + paint("text", title_c)
                rows.append(pad(colored, w - len(ident) - 1) + " " + paint("dim", ident))
        if not n:
            rows.append(paint("faint", "  —"))
        blocks.append([pad(r, w) for r in rows] + [" " * w] * (CH - len(rows)))
    return [" " * margin + ln for ln in hcat(blocks, gap)]


def flow_node(x, name, who, model, status):
    iw = 12
    kind = status if status != "pending" else "faint"
    body = [paint(status if status != "pending" else "dim", center(f"{x.glyph(status)} {name}", iw)),
            paint("dim", center(clip(who, iw), iw)), paint("dim", center(clip(model, iw), iw))]
    return box(body, 14, 5, kind=kind)


def screen_flow(x):
    cfg, r = x.cfg, x.cfg["roles"]
    found = list(x.project.glob(f"board/*/{x.card_id}.md")) if x.card_id else []
    area = Card(found[0]).area if found else "backend"
    st = ["ok" if x.card_id else "pending"] + x.stat
    qa_n, cross_n = [rv["name"] for rv in cfg["reviewers"]][:2]
    short = lambda m: (m or "-").split("-")[0]  # noqa: E731
    nodes = [("CARD", "trigger", f"#{(x.card_id or '-').split('-')[0]}"), ("SPLIT", "splitter", r["splitter"]["model"] if cfg["split"] else "off"),
             ("PLAN", "planner", r["planner"]["model"]), ("BUILD", "builder", r["builder"]["model"]), ("CHECKS", "rules + ci", "lint+tests"),
             ("REVIEW", "qa + cross", f"{short(cfg['reviewers'][0].get('model'))[:6]}+{short(cfg['reviewers'][1].get('model'))[:5]}"), ("MERGE", "git", cfg["base"])]
    g = {"ok": paint("ok", "✓"), "fail": paint("fail", "×"), "running": paint("running", x.spin), "pending": paint("dim", "·")}
    details = [paint("dim", area), paint("dim", "3+ parts"), paint("dim", f"{area}.md"), paint("dim", cfg["agents"].get(area, "backend")),
               paint("dim", f"{len(cfg['guardrails']['protected'])} rules"), f"qa {g[x.revs[qa_n]]}  cross {g[x.revs[cross_n]]}", paint("dim", "retro + log")]
    boxes = [flow_node(x, n, w, m, st[i]) for i, (n, w, m) in enumerate(nodes)]
    rows = []
    for k in range(5):
        row = "  "
        for i in range(7):
            row += boxes[i][k]
            if i < 6:
                row += paint("ok" if st[i] == "ok" else "faint", "──▶") if k == 2 else "   "
        rows.append(row + "  ")
    rows.append("  " + "   ".join(center(d, 14) for d in details) + "  ")
    tries = x.tries()
    if tries and x.cur is not None:
        dots = "".join(paint("running", "●") if i < tries else paint("faint", "○") for i in range(cfg["max_attempts"]))
        rows.append(" " + paint("dim", "  attempt ") + dots)
    else:
        rows.append("")
    rows += ["", " " + rule(W - 2, "Activity")]
    room = min(CH - len(rows), 9)
    rows += [event_line(e, W) for e in x.ev[-room:]] or [paint("faint", "   nothing yet")]
    return rows


def wrap(text, w, indent=""):
    text = clean(text)
    out = []
    for para in text.splitlines():
        out += textwrap.wrap(para, w, initial_indent=indent, subsequent_indent=indent) or [""]
    return out


def checklist(text, w):
    """'- [x] task' lines -> '✓ task' / '○ task' with a hanging indent when wrapped."""
    text = clean(text)
    out = []
    for ln in text.splitlines():
        m = re.match(r"\s*- \[( |x)\] (.*)", ln)
        if not m:
            out += wrap(ln, w)
            continue
        parts = textwrap.wrap(m.group(2), w - 2) or [""]
        out.append((paint("ok", "✓") if m.group(1) == "x" else paint("dim", "○")) + " " + parts[0])
        out += ["  " + p for p in parts[1:]]
    return out


def card_lines(card, w):
    L = [paint("accent", clip(card.title, w)), paint("dim", f"{card.id.split('-')[0]} · {card.area} · {card.get('attempts', '0')} {'try' if card.get('attempts', '0') == '1' else 'tries'}")]

    def sec(t, kind="accent"):
        L.extend(["", rule(w, t, tkind=kind)])

    sec("Goal")
    L += wrap(card.section("Goal"), w)
    sec("Criteria")
    L += checklist(card.section("Acceptance criteria"), w) or [paint("dim", "—")]
    sec("Plan")
    L += wrap(card.section("Plan"), w) or [paint("dim", "not planned yet")]
    sec("Tasks")
    L += checklist(card.section("Tasks"), w) or [paint("dim", "none yet")]
    q = card.section("Blockers")
    if q:
        sec("Questions for you", "fail")
        L += [paint("fail", ln) for ln in wrap(q, w)]
        if card.path.parent.name == "blocked":
            L += ["", paint("info", "press a to answer these")]
    sec("Log", "dim")
    L += [paint("dim", ln) for ln in wrap("\n".join(card.section("Status log").splitlines()[-4:]), w)]
    return L


def screen_planner(x):
    flat = x.flat()
    if flat and not x.selected:
        x.ui.col, x.ui.row = flat[0]
    glyph = {"backlog": ("○", "dim"), "doing": ("●", "running"), "done": ("✓", "ok"), "blocked": ("×", "fail")}
    left = [" " + rule(37, "Cards"), ""]
    for ci, ri in flat:
        key = COLS[ci][1]
        c = x.items[key][ri]
        g, kind = glyph[key]
        s = f" {g} {clip(c.title, 33)}"
        left.append(selrow(s, 38) if (ci, ri) == (x.ui.col, x.ui.row) else paint(kind, s[:3]) + paint("text", s[3:]))
    if not flat:
        left.append(paint("faint", "  no cards yet"))
    sel = x.selected if x.selected else (x.items[COLS[x.ui.col][1]][x.ui.row] if flat else None)
    right = []
    if x.ui.mode == "answer":
        right = [" " + ln for ln in answer_view(x.ui, 76)]
    elif sel:
        allr = card_lines(sel, 76)
        x.ui.scroll = min(max(x.ui.scroll, 0), max(len(allr) - CH, 0))
        right = [" " + ln for ln in allr[x.ui.scroll: x.ui.scroll + CH]]
        if len(allr) > CH:
            right[-1] = " " + paint("dim", "PgUp/PgDn for more ▾")
    sep = paint("faint", "│")
    left, right = fit(left, CH, 40), fit(right, CH, 79)
    return [f"{a}{sep}{b}" for a, b in zip(left, right, strict=True)]


def answer_view(ui, w):
    """The detail pane while answering: current question, what is being typed, answers given so far."""
    n, total = len(ui.ans) + 1, len(ui.qs)
    L = [paint("accent", f"Answering {ui.qcard.split('-')[0]}") + paint("dim", f"   question {n} of {total}"), rule(w), ""]
    L += [paint("bold", ln) for ln in wrap(ui.qs[len(ui.ans)], w)]
    opts = ui.qopts[len(ui.ans)] if len(ui.qopts) > len(ui.ans) else []
    if opts:
        L.append("")
        for i, o in enumerate(opts, 1):
            lines = wrap(o, w - 6)
            L.append("  " + paint("running", str(i)) + "  " + paint("text", lines[0]))
            L += ["     " + paint("text", ln) for ln in lines[1:]]
    if ui.suggesting and not opts:
        L += ["", paint("running", "\u2807 asking Claude for 3 suggested answers (a few seconds)... you can already type your own")]
    L += ["", paint("dim", f"Your answer   (press 1-{len(opts)} to pick a suggestion, or type your own)" if opts else "Your answer")]
    typed = wrap(ui.buf + "\u258c", w - 2)
    L += [(paint("info", "\u203a ") if i == 0 else "  ") + ln for i, ln in enumerate(typed)]
    if ui.ans:
        L += ["", rule(w, "Done so far", "faint", "dim")]
        L += [paint("ok", "\u2713 ") + paint("dim", f"{i} ") + paint("text", clip(a or "(skipped)", w - 6)) for i, a in enumerate(ui.ans, 1)]
    L += ["", paint("dim", "Enter next question  \u00b7  Esc cancel  \u00b7  leave empty to skip")]
    return L


def _bg(fn):
    """Run fn without blocking the panel (tests replace this to run it at once)."""
    import threading
    threading.Thread(target=fn, daemon=True).start()


def _fill_suggestions(ui, card):
    """Background job. Must never raise: it runs while the user answers, and the card may be answered and moved before it finishes."""
    try:
        answer.add_suggestions(card)
        if ui.mode == "answer" and ui.qcard == card.id:
            ui.qopts = [q.options for q in answer.parse(card)]
    except Exception:           # noqa: BLE001  (card moved/removed meanwhile, Claude unreachable, odd reply): the user can still type
        pass
    finally:
        ui.suggesting = False


def start_answer(x):
    """Begin answering the selected card (it must be blocked and have questions)."""
    c, ui = x.selected, x.ui
    if not c or c.path.parent.name != "blocked":
        ui.msg = "select a card in Needs you to answer its questions"
        return
    parsed = answer.parse(c)
    if not parsed:
        ui.msg = f"{c.id.split('-')[0]} has no questions to answer"
        return
    ui.qopts = [q.options for q in parsed]
    ui.mode, ui.qcard, ui.qs, ui.ans, ui.buf, ui.msg, ui.screen = "answer", c.id, [q.text for q in parsed], [], "", "", 2
    if answer.missing_options(c):                        # an older card, or an agent that forgot: ask Claude for the 3 suggestions now
        ui.suggesting = True
        _bg(lambda: _fill_suggestions(ui, c))


def answer_key(key, ui, x):
    """Every key while answering. With nothing typed yet, 1/2/3 pick that suggestion and move on; otherwise keys are text (q too)."""
    opts = ui.qopts[len(ui.ans)] if len(ui.qopts) > len(ui.ans) else []
    if not ui.buf and len(key) == 1 and key.isdigit() and 1 <= int(key) <= len(opts):
        ui.buf, key = opts[int(key) - 1], "\r"
    if key in ("\r", "\n"):
        ui.ans.append(ui.buf.strip())
        ui.buf = ""
        if len(ui.ans) == len(ui.qs):
            card = next((c for c in x.items["blocked"] if c.id == ui.qcard), None)
            done = bool(card) and answer.apply(card, ui.qs, ui.ans)
            ui.msg = f"{ui.qcard.split('-')[0]} answered and queued \u00b7 press r to run" if done else "nothing answered, card left as it was"
            ui.mode = None
    elif key == "\x1b":
        ui.mode, ui.msg = None, "answer cancelled"
    elif key in ("\x7f", "\x08"):
        ui.buf = ui.buf[:-1]
    elif len(key) == 1 and key >= " ":
        ui.buf += key


def request_title(text):
    first = re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0]
    return first[:60].rstrip(" .,;:") or "request"


def screen_new(x):
    ui, w = x.ui, 100
    L = [" " + rule(w, "New request: say what you want changed", "faint", "accent"), "",
         paint("dim", " Write it in plain words. When you press Enter the card is created and the pipeline starts working on it."),
         paint("dim", " A vague request is fine: the planner will ask you questions instead of guessing."), ""]
    typed = wrap(ui.buf + "\u258c", w - 4)
    L += [(paint("info", " \u203a ") if i == 0 else "   ") + ln for i, ln in enumerate(typed[-12:])]
    L += ["", " " + paint("dim", "Built by the ") + paint("accent", ui.area) + paint("dim", " agent   (Tab changes it)")]
    return L


def new_key(key, ui, x, runner):
    """Every key while writing a new request (q, digits and letters are text here)."""
    if key in ("\r", "\n"):
        text = " ".join(ui.buf.split())
        if not text:
            ui.mode, ui.msg = None, "nothing written, no card created"
            return
        path = create_card(x.project, request_title(text), ui.area, goal=text,
                           criteria=["The request in the Goal is fulfilled, checked by tests or commands the plan names"])
        ui.mode, ui.buf = None, ""
        runner.start()                                  # a run already in progress picks the new card up on its own
        ui.msg = f"{path.stem.split('-')[0]} created and queued \u00b7 the pipeline is working on it"
    elif key == "\x1b":
        ui.mode, ui.msg = None, "request cancelled"
    elif key == "\t":
        areas = config.areas(x.cfg)
        ui.area = areas[(areas.index(ui.area) + 1) % len(areas)] if ui.area in areas else areas[0]
    elif key in ("\x7f", "\x08"):
        ui.buf = ui.buf[:-1]
    elif len(key) == 1 and key >= " ":
        ui.buf += key


def tail_lines(path, n, w):
    try:
        data = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in data[-80:]:
        if not ln.strip() or ln.startswith(("--- run", "  (+", "==")):
            continue
        kind = "info" if ln.startswith("> ") else "accent" if ln.startswith(("RESULT:", "VERDICT:")) else "dim"
        out.append(paint(kind, clip(ln.strip(), w)))
    return out[-n:]


def screen_agents(x):
    sd = x.project / ".orchestrator" / "streams"
    ph = x.phase.split()[0] if x.cur is not None else ""
    active = {"planner": ph in ("split", "plan"), "builder": ph == "build", "qa": ph == "review", "cross": ph == "review", "retro": ph == "retro",
              "pipeline": x.cur is not None}
    model = {"planner": x.cfg["roles"]["planner"]["model"], "builder": x.cfg["roles"]["builder"]["model"], "retro": x.cfg["roles"]["retro"]["model"],
             "qa": x.cfg["reviewers"][0].get("model", ""), "cross": x.cfg["reviewers"][1].get("model", ""), "pipeline": ""}
    widths, heights = [40, 39, 39], [15, 14]
    rows = []
    for ri, names in enumerate([["planner", "builder", "qa"], ["cross", "retro", "pipeline"]]):
        blocks = []
        for ci, n in enumerate(names):
            w, h = widths[ci], heights[ri]
            on = active[n] and n != "pipeline"
            body = [" " + ln for ln in (tail_lines(sd / f"{n}.log", h - 2, w - 4) if n != "pipeline" else [event_line(e, w - 2).strip() for e in x.ev[-(h - 2):]])]
            blocks.append(box(body, w, h, f"{x.spin if on else '●'} {n}", "running" if on else "faint", clip(model[n], 16), tkind="running" if on else "text"))
        rows += hcat(blocks)
    return rows


# ------------------------------------------------------------------- usage numbers
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
    return paint(kind, "█" * full) + paint("faint", "░" * (width - full))


def window_line(label, w, now):
    """One account-limit window of Claude Code, e.g. the 5-hour session."""
    if not w or w.get("utilization") is None:
        return f" {label:<9}" + paint("dim", "no data yet")
    reset = w.get("resetsAt") or 0
    if reset and reset < now:
        return f" {label:<9}" + paint("dim", "reset since · press u")
    frac = w["utilization"]
    return f" {label:<9}{bar(frac)} {round(frac * 100):>3}%  " + paint("dim", f"resets in {fmt_eta(reset - now)}" if reset else "")


def budget_lines(x, ai):
    """Your own limits for this AI (config `budgets`): used / limit over a rolling window, as bars."""
    out = []
    for b in x.budgets:
        if b["key"].split("/")[0] != ai:
            continue
        used = f"${b['used']:.2f}/${b['limit']:g}" if b["unit"] == "cost" else f"{fmt_n(int(b['used']))}/{fmt_n(int(b['limit']))} {b['unit']}"
        out.append(f" {clip(b['key'], 9):<9}{bar(min(b['frac'], 1))} {round(b['frac'] * 100):>3}%  " + paint("dim", f"{used} per {b['per']}" + (" ~" if b["est"] else "")))
    return out


def usage_table(run, total, ai):
    """model | calls | tokens this run | tokens in all runs."""
    models = sorted(set(run.get(ai, {})) | set(total.get(ai, {})))
    if not models:
        return [paint("faint", "   no calls yet")]
    out = [paint("dim", f" {'model':<20}{'calls':>6}{'this run':>11}{'all runs':>11}")]
    for m in models:
        a, b = run.get(ai, {}).get(m), total.get(ai, {}).get(m)
        mark = lambda v: ("~" if v and v.get("est") else "") + (fmt_n(v["in"] + v["out"]) if v else "·")  # noqa: E731  (~ = estimated, the CLI reports no tokens)
        out.append(f" {clip(m, 20):<20}{(a or {'calls': 0})['calls']:>6}{mark(a):>11}{mark(b):>11}")
    return out


def usage_summary(x):
    """Compact usage for the header: Claude's account windows and agy's token count."""
    now = time.time()
    w = x.limits.get("windows", {})
    parts = []
    for key, label in (("five_hour", "5h"), ("seven_day", "wk")):
        win = w.get(key)
        if win and win.get("utilization") is not None and not (win.get("resetsAt") and win["resetsAt"] < now):
            f = win["utilization"]
            parts.append(label + " " + paint("ok" if f < 0.6 else "running" if f < 0.85 else "fail", f"{round(f * 100)}%"))
    claude = " ".join(parts) or paint("dim", "limits ?")
    agy_tok = sum(m["in"] + m["out"] for m in x.all_use.get("agy", {}).values())
    return claude, (f"{fmt_n(agy_tok)} tok" if agy_tok else "")


def ai_rows(x):
    """Checklist rows: ('head', text) or ('item', key). Items are the selectable AI models."""
    rows, reg = [], providers.registry(x.cfg)
    clis = ["claude", "agy"] + [c for c, v in x.ais.items() if c not in ("claude", "agy") and v.get("installed")]
    for cli in clis:
        spec = reg.get(cli) or {}
        label = spec.get("name") or x.ais.get(cli, {}).get("name") or cli
        info = x.ais.get(cli, {})
        state = "logged in" if info.get("logged_in") else ("not logged in" if info.get("installed") else "not installed")
        rows.append(("head", cli, label, state if info else "not detected \u00b7 press d"))
        if info and not info.get("logged_in"):
            rows.append(("hint", spec.get("login_hint" if info.get("installed") else "install_hint", "")))
        rows += [("item", menu.keyof(c, m)) for c, m in x.avail if c == cli]
    return rows


def short_key(key):
    cli, model = key.split("/", 1)
    return model if cli == "claude" else f"{cli} · {model}"


def screen_ais(x):
    rows = ai_rows(x)
    items = [r[1] for r in rows if r[0] == "item"]
    total = len(items) + len(menu.SLOTS)
    x.ui.cursor = min(max(x.ui.cursor, 0), max(total - 1, 0))
    cur = x.ui.cursor
    used = {}
    for s in menu.SLOTS:
        used.setdefault(menu.assigned(x.cfg, s), []).append(s)
    lw = 57
    # --- checklist
    lines, sel_line = [], 0
    for r in rows:
        if r[0] == "hint":
            lines.append("   " + paint("running", "\u2192 ") + paint("dim", clip(r[1], lw - 8)))
            continue
        if r[0] == "head":
            _, cli, label, state = r
            ok = state == "logged in"
            lines.append(" " + paint("bold", label) + "  " + paint("ok" if ok else "dim", "● " if ok else "○ ") + paint("dim", state))
            continue
        key = r[1]
        idx = items.index(key)
        tag = clip(" ".join(used.get(key, [])), 27)
        plain = f"   {'◉' if key in x.on else '○'} {clip(key.split('/', 1)[1], 24):<25}{tag}"
        if idx == cur:
            sel_line = len(lines)
            lines.append(selrow(plain, lw))
        else:
            lines.append("   " + (paint("ok", "◉") if key in x.on else paint("faint", "○")) + " " + paint("text" if key in x.on else "dim", f"{clip(key.split('/', 1)[1], 24):<25}")
                         + paint("info", tag))
    room = CH - 13
    start = min(max(sel_line - room // 2, 0), max(len(lines) - room, 0))
    out = [" " + rule(lw - 9, "Use these AIs") + paint("dim", f" {len(x.on)} on ")]
    out += (lines[start:start + room] or [paint("dim", "   no AI detected · press d")])
    out += [""] * (1 + room - len(out) + 1 - 1)
    out = out[: room + 1] + [" " + rule(lw - 2, "Who does what")]
    for i, slot in enumerate(menu.SLOTS):
        key = menu.assigned(x.cfg, slot)
        ok = key in x.on or x.cfg.get("use") is None
        val = short_key(key)
        if len(items) + i == cur:
            out.append(selrow(f"   {slot:<10}‹ {clip(val, 34)} ›", lw))
        else:
            out.append(f"   {paint('text', f'{slot:<10}')}" + paint("text" if ok else "fail", f"  {clip(val, 34)}") + ("" if ok else paint("fail", " !")))
        if slot == "suggester":
            out.append(" " + paint("faint", "   reviewers"))
    same = menu.assigned(x.cfg, "qa") == menu.assigned(x.cfg, "cross")
    out.append(" " + (paint("running", "  ! qa and cross use the same model") if same else ""))
    left = fit(out, CH, lw)
    # --- usage
    now = time.time()
    w = x.limits.get("windows", {})
    upd = x.limits.get("updated")
    u = [" " + rule(60, "Usage · live"), "",
         " " + paint("bold", "Claude Code") + paint("dim", f"   account limits · {'updated ' + fmt_eta(now - upd) + ' ago' if upd else 'never read'}"),
         window_line("session", w.get("five_hour"), now), window_line("week", w.get("seven_day"), now)]
    if x.limits.get("status") not in (None, "allowed", "allowed_warning"):
        u.append(paint("fail", f" status: {x.limits.get('status')}"))
    u += [""] + usage_table(x.run_use, x.all_use, "claude") + budget_lines(x, "claude")
    u += ["", " " + paint("bold", "Antigravity") + paint("dim", "   quota not shown by agy · set a budget in config")] + usage_table(x.run_use, x.all_use, "agy") + budget_lines(x, "agy")
    for cli in sorted(c for c in x.all_use if c not in ("claude", "agy")):
        u += ["", " " + paint("bold", x.ais.get(cli, {}).get("name") or cli) + paint("dim", "   ~ = estimated tokens")] + usage_table(x.run_use, x.all_use, cli) + budget_lines(x, cli)
    probe = usage.PROBE
    u += ["", " " + paint("info", ("⠿ " if probe["running"] else "") + (x.ui.msg or probe["msg"]))]
    right = fit(u, CH, 62)
    sep = paint("faint", "│")
    return [f"{a}{sep}{b}" for a, b in zip(left, right, strict=True)]


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


def check_line(status, title, hint, w):
    g = {"ok": paint("ok", "\u2713"), "warn": paint("running", "!"), "fail": paint("fail", "\u00d7")}[status]
    out = [" " + g + " " + paint("text" if status == "ok" else "bold", clip(title, w - 4))]
    out += ["     " + paint("dim", ln) for ln in wrap(hint, w - 6)] if hint else []
    return out


def screen_settings(x):
    ui = x.ui
    n = len(settings.SPEC)
    ui.scur = min(max(ui.scur, 0), n - 1)
    if not ui.checks or time.time() - ui.checks_t > 3:                 # a few git calls: refresh every few seconds, not every frame
        ui.checks, ui.checks_t = checks.readiness(x.project), time.time()
    lw = 62
    left = [" " + rule(lw - 2, "Settings"), ""]
    for i, (key, label, kind, _o, _u, _h) in enumerate(settings.SPEC):
        val = clip(settings.show(settings.get(x.cfg, key), key), 30)
        if i == ui.scur:
            left.append(selrow(f"   {label:<26}" + (f"\u2039 {val} \u203a" if kind != "text" else f"{val}"), lw))
        else:
            left.append(f"   {paint('text', f'{label:<26}')}" + paint("ok" if val == "on" else "dim" if val == "off" else "text", val))
    cur = settings.SPEC[ui.scur]
    left += ["", " " + rule(lw - 2, f"Editing {cur[1]}" if ui.mode == "edit" else "About this setting")]
    if ui.mode == "edit":
        typed = wrap(ui.buf + "\u258c", lw - 6)
        left += [paint("info", "   \u203a ") + typed[0]] + ["     " + t for t in typed[1:]]
        left += ["", paint("dim", "   Enter save  \u00b7  Esc cancel")]
    else:
        left += ["   " + paint("dim", ln) for ln in wrap(cur[5], lw - 6)]
        left += ["", paint("info", "   Enter to edit the text") if cur[2] == "text" else paint("faint", "   \u2190/\u2192 or space to change")]
    # readiness
    ready, text = checks.summary(ui.checks)
    warns = any(c[0] == "warn" for c in ui.checks)
    right = [" " + rule(54, "Ready to run?"), " " + paint("ok" if ready and not warns else "running" if ready else "fail", ("\u2713 " if ready and not warns else "") + text), ""]
    for st, title, hint in ui.checks:
        right += check_line(st, title, hint, 55)
    sep = paint("faint", "\u2502")
    return [f"{a}{sep}{b}" for a, b in zip(fit(left, CH, lw), fit(right, CH, 57), strict=True)]


def handle_settings(key, ui, x):
    """Keys of the Settings tab. True when the key was consumed."""
    cur = settings.SPEC[ui.scur]
    if key in ("up", "down"):
        ui.scur = (ui.scur + (-1 if key == "up" else 1)) % len(settings.SPEC)
    elif key in ("left", "right"):
        ui.msg, ui.checks_t = settings.change(x.project, cur[0], -1 if key == "left" else 1), 0.0
    elif key in (" ", "\r", "\n"):
        if cur[2] == "text":
            ui.mode, ui.edit_key, ui.buf = "edit", cur[0], str(settings.get(x.cfg, cur[0]))
        else:
            ui.msg, ui.checks_t = settings.change(x.project, cur[0], 1), 0.0
    else:
        return False
    return True


def edit_key(key, ui, x):
    """Every key while editing a text setting (q, digits and letters are text here)."""
    if key in ("\r", "\n"):
        ui.msg, ui.mode, ui.checks_t = settings.set_text(x.project, ui.edit_key, ui.buf), None, 0.0
    elif key == "\x1b":
        ui.mode, ui.msg = None, "edit cancelled"
    elif key in ("\x7f", "\x08"):
        ui.buf = ui.buf[:-1]
    elif len(key) == 1 and key >= " ":
        ui.buf += key


SCREENS = [screen_board, screen_flow, screen_planner, screen_agents, screen_ais, screen_settings]


# --------------------------------------------------------------------------- frame
def frame(x):
    claude_use, agy_use = usage_summary(x)
    extra = {"claude": claude_use, "agy": agy_use}
    pills = "   ".join(f"{paint('ok', '●') if v.get('logged_in') else paint('fail', '●')} {k} {extra.get(k, '')}".rstrip() for k, v in x.ais.items()) \
        or paint("dim", "run `lonerchestrator intro`")
    left = paint("accent", " ◆ lonerchestrator") + paint("faint", "  ·  ") + paint("text", x.project.name)
    head = left + " " * max(W - vlen(left) - vlen(pills) - 1, 1) + pills + " "
    tabs = " ".join(paint("tab", f" {i + 1} {n} ") if i == x.ui.screen else paint("dim", f" {i + 1} {n} ") for i, n in enumerate(TABS))
    run = x.proc_msg or (paint("running", f"{x.spin} running") if x.cur is not None else paint("faint", "● idle"))
    tabs_line = " " + tabs + " " * max(W - vlen(tabs) - vlen(run) - 2, 1) + run + " "
    if x.ui.mode == "new":
        keys = " type your request   Enter create it and start   Tab agent   Esc cancel   Backspace erase"
    elif x.ui.mode == "answer":
        keys = " 1-3 pick a suggestion   or type your own   Enter next question   Esc cancel   Backspace erase"
    elif x.ui.mode == "edit":
        keys = " type the new value   Enter save   Esc cancel   Backspace erase"
    elif x.ui.screen == 5:
        keys = " \u2191\u2193 move   \u2190\u2192 / space change   Enter edit text   1-6 tabs   q quit"
    elif x.ui.screen == 4:
        keys = " \u2191\u2193 move   space toggle   \u2190\u2192 model   u refresh limits   d detect   1-6 tabs   q quit"
    else:
        keys = " \u2190\u2192\u2191\u2193 move   tab / 1-6 views   n new request   a answer   r run   x stop   PgUp PgDn scroll   q quit"
    body = fit(screen_new(x) if x.ui.mode == "new" else SCREENS[x.ui.screen](x), CH)
    lines = [pad(clip_ansi(head, W), W), pad(clip_ansi(tabs_line, W), W), paint("faint", "─" * W)] + body \
        + [pad(clip_ansi(" " + x.now(), W), W), paint("faint", pad(keys, W))]
    return [keep_sgr(ln) for ln in lines]            # last line of defense: nothing but our own color codes reaches the terminal


def render(project, screen=0, ui=None, color=True, proc_msg=""):
    """Whole screen as a string: exactly H lines, each exactly W visible columns."""
    global COLOR
    COLOR = color
    ui = ui or UI()
    ui.screen = screen
    return "\n".join(frame(Ctx(project, ui, proc_msg)))


# --------------------------------------------------------------------------- interactive loop
class Runner:
    """Starts/stops the pipeline as a background process owned by the panel."""

    def __init__(self, project, base):
        self.project, self.base, self.proc = project, base, None

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
            return paint("ok", "✓ run finished")
        tail = (self.project / ".orchestrator" / "run.out").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:]
        return paint("fail", clip(f"× run stopped (rc {rc}): {tail[0] if tail else ''}", 60))


def handle(key, ui, x, runner):
    n = len(COLS)
    if ui.mode == "new":
        new_key(key, ui, x, runner)
        return
    if ui.mode == "answer":
        answer_key(key, ui, x)
        return
    if ui.mode == "edit":
        edit_key(key, ui, x)
        return
    ui.msg = "" if ui.screen != 4 else ui.msg
    if key == "n" and ui.screen in (0, 1, 2):
        ui.mode, ui.buf, ui.msg = "new", "", ""
    elif key == "a" and ui.screen in (0, 2):
        start_answer(x)
    elif key and key in "123456":
        ui.screen, ui.scroll = int(key) - 1, 0
    elif key == "\t":
        ui.screen, ui.scroll = (ui.screen + 1) % len(TABS), 0
    elif ui.screen == 4 and handle_ais(key, ui, x):
        pass
    elif ui.screen == 5 and handle_settings(key, ui, x):
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
                    if k == "\x03" or (k == "q" and not ui.mode):    # Ctrl+C, or q (but q is text while answering)
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
