"""Regenerates the README screenshots (docs/images/*.png) from a made-up demo project, so they never show real data.

    python docs/screenshots.py

Needs Microsoft Edge or Google Chrome on this machine (headless, nothing is installed). It builds the fictional "orbit-shop" project in a temp folder,
serves it with the real web page, and captures every view in light and dark. The terminal panel is rendered by the real code and drawn as HTML."""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "images"
EDGES = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
         r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
NOW = time.time()

CARDS = {
    "done": [
        ("001-product-search", "Add product search with filters", "both", 2,
         "Shoppers can search the catalogue by name and narrow it by category and price.",
         ["Typing in the search box lists matching products within 300 ms", "The category and price filters combine", "`python -m pytest tests/test_search.py` passes"],
         ["Index product name and category on startup", "Add GET /api/search with q, category, min_price, max_price", "Wire the search box and the filter chips to it", "Cover the filters with tests"], 4),
        ("002-checkout-validation", "Validate the checkout form on the client", "frontend", 1,
         "Show what is wrong with the checkout form before the shopper presses Pay.",
         ["An empty or invalid email shows an inline message", "The Pay button stays disabled until the form is valid"],
         ["Add a validation helper for email, postcode and card number", "Show inline errors under each field", "Disable Pay while invalid"], 3),
    ],
    "doing": [
        ("005-order-export-csv", "Export orders as CSV", "backend", 1,
         "Store managers can download the orders of a date range as a CSV file.",
         ["GET /api/orders.csv?from=&to= returns one row per order line", "Dates outside the range are not included", "A range of 10,000 orders streams without loading it all in memory"],
         ["Add the date-range query to the orders repository", "Stream rows through csv.writer", "Add the endpoint and its content type", "Test an empty range", "Test a 10,000 order range"], 2),
        ("006-dark-mode", "Dark mode for the storefront", "frontend", 1,
         "The storefront follows the shopper's system theme and has a manual switch in the header.",
         ["The page follows prefers-color-scheme on first visit", "The header switch overrides it and is remembered", "Text keeps a contrast ratio of at least 4.5:1 in both modes"],
         ["Move colours to CSS variables", "Add the dark palette", "Add the header switch and store the choice", "Check contrast of every text colour"], 4),
    ],
    "blocked": [
        ("004-refund-flow", "Refund a partially shipped order", "backend", 0,
         "A store manager can refund an order when only some of its items were shipped.", ["Refunding an order returns the money for the unshipped items", "The order shows what was refunded and why"], [], 0),
    ],
    "backlog": [
        ("007-rate-limit-api", "Rate limit the public API", "backend", 0, "Stop a single client from overloading the public API.", ["More than 60 requests a minute from one key gets HTTP 429"], [], 0),
        ("008-email-receipts", "Send order receipts by email", "backend", 0, "Send the shopper a receipt as soon as an order is paid.", ["A paid order sends one email with the order lines and the total"], [], 0),
        ("009-product-images", "Resize product images on upload", "both", 0, "Product photos should load fast on phones.", ["Uploaded images are stored in 3 sizes", "The catalogue uses the smallest size that fits"], [], 0),
    ],
}
QUESTIONS = [
    ("Should the refund go back to the original payment method, or become store credit?",
     ["Original payment method only", "Original payment method, with store credit as an option the manager picks", "Store credit only"]),
    ("What should happen to the shipping fee of items that were already shipped?",
     ["Keep the shipping fee (it was used)", "Refund shipping in proportion to the unshipped items", "Let the manager decide per refund"]),
    ("Who is allowed to refund?",
     ["Only users with the manager role", "Managers and support agents, with a limit per day", "Any signed in staff member"]),
]

# The Python side of orbit-shop and one card's change to it: what the Change graph view draws (graph.py reads it from git like any card).
SHOP = {
    "api/__init__.py": "",
    "api/repo.py": '''"""Orders storage (SQLite)."""
import sqlite3


class OrderRepo:
    def __init__(self, path):
        self.db = sqlite3.connect(path)

    def order(self, order_id):
        return self.db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    def lines(self, order_id):
        return self.db.execute("SELECT * FROM order_lines WHERE order_id = ?", (order_id,)).fetchall()
''',
    "api/routes.py": '''"""HTTP routes of the shop API."""
from .repo import OrderRepo


def get_order(repo: OrderRepo, order_id):
    return {"order": repo.order(order_id), "lines": repo.lines(order_id)}
''',
    "api/reports.py": '''"""The daily report for the store manager."""
from .repo import OrderRepo


def daily_report(repo: OrderRepo, ids):
    return [repo.order(i) for i in ids]
''',
}
EXPORT_CHANGE = {
    "api/repo.py": SHOP["api/repo.py"] + '''
    def orders_between(self, start, end):
        """Order lines whose order date is in [start, end], oldest first, one at a time."""
        yield from self.db.execute("SELECT o.id, o.created, l.sku, l.qty, l.price FROM orders o JOIN order_lines l ON l.order_id = o.id "
                                   "WHERE o.created BETWEEN ? AND ? ORDER BY o.created", (start, end))
''',
    "api/export.py": '''"""Orders as CSV, streamed row by row."""
import csv
import io

from .repo import OrderRepo

HEADER = ["order", "date", "sku", "qty", "price"]


def csv_rows(repo: OrderRepo, start, end):
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(HEADER)
    for row in repo.orders_between(start, end):
        out.writerow(row)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()
''',
    "api/routes.py": SHOP["api/routes.py"].replace("from .repo import OrderRepo\n", "from .export import csv_rows\nfrom .repo import OrderRepo\n") + '''

def export_orders(repo: OrderRepo, start, end):
    return {"content_type": "text/csv", "body": csv_rows(repo, start, end)}
''',
    "tests/test_export.py": '''from api.export import HEADER, csv_rows


class FakeRepo:
    def orders_between(self, start, end):
        return [(1, "2026-11-01", "MUG-01", 2, 9.5)]


def test_csv_has_a_header_and_the_rows():
    text = "".join(csv_rows(FakeRepo(), "2026-11-01", "2026-11-30"))
    assert text.splitlines()[0] == ",".join(HEADER)
''',
}
DEMO = {}


def write(p, files):
    for path, text in files.items():
        (p / path).parent.mkdir(parents=True, exist_ok=True)
        (p / path).write_text(text, encoding="utf-8", newline="\n")


def demo_graph(p, run):
    """Card 005's first attempt as a branch, graphed by the real code and saved where the pipeline saves it."""
    from orch import config, graph
    cid = "005-order-export-csv"
    subprocess.run(["git", "checkout", "-qb", f"card/{cid}"], cwd=p, check=True)
    write(p, EXPORT_CHANGE)
    subprocess.run(["git", "add", "api", "tests"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "Export orders as CSV"], cwd=p, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=p, check=True)
    m = graph.build(p, "main", f"card/{cid}", card=cid, attempt=1, guard=config.load(p)["guardrails"], source="pipeline")
    (run / cid).mkdir(parents=True, exist_ok=True)
    (run / cid / "graph1.json").write_text(graph.dumps(m), encoding="utf-8")
    DEMO["sel"] = next(s["id"] for f in m["files"] for s in f["symbols"] if s["qual"] == "csv_rows")


def card_text(cid, title, area, attempts, goal, crit, tasks, done, extra=""):
    t = f"---\ntitle: {title}\narea: {area}\nattempts: {attempts}\n---\n# {title}\n\n## Goal\n{goal}\n\n## Acceptance criteria\n" + "".join(f"- [ ] {c}\n" for c in crit)
    t += "\n## Out of scope\n- anything not named above\n\n## Plan\n"
    t += ("Reuse the existing helpers and keep the change small: " + "; ".join(tasks[:2]).lower() + ".\n") if tasks else "\n"
    t += "\n## Tasks\n" + "".join(f"- [{'x' if i < done else ' '}] {x}\n" for i, x in enumerate(tasks))
    t += "\n## Blockers / questions\n" + extra + "\n## Answers\n\n## Status log\n"
    t += f"- {time.strftime('%F %T', time.localtime(NOW - 31 * 60))} started on card/{cid} (base main)\n" if done or attempts else ""
    return t


def build_project(root):
    from orch import cli, config, folder, trust, usage
    home = root / "home"
    home.mkdir()
    os.environ["LONERCHESTRATOR_HOME"] = str(home)                  # before `init`: the demo's folder lives here, never in your own
    p = root / "orbit-shop"
    p.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "Alex Moreno", "GIT_AUTHOR_EMAIL": "alex@orbit-shop.example", "GIT_COMMITTER_NAME": "Alex Moreno", "GIT_COMMITTER_EMAIL": "alex@orbit-shop.example"}
    os.environ.update(env)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
    (p / "README.md").write_text("# Orbit Shop\n\nA small online shop: a Python API and a plain HTML storefront.\n", encoding="utf-8")
    (p / "pyproject.toml").write_text('[project]\nname = "orbit-shop"\n[tool.pytest.ini_options]\n[tool.ruff]\n', encoding="utf-8")
    (p / "tests").mkdir()
    (p / "tests" / "test_search.py").write_text("def test_search():\n    assert True\n", encoding="utf-8")
    write(p, SHOP)
    cli.main(["-C", str(p), "init"])
    h = folder.of(p)
    raw = {"base": "main", "parallel": 2, "builders": 2,
           "roles": {"splitter": {"cli": "claude", "model": "haiku"}, "planner": {"cli": "claude", "model": "sonnet"}, "builder": {"cli": "claude", "model": "sonnet"},
                     "retro": {"cli": "claude", "model": "sonnet"}, "suggester": {"cli": "claude", "model": "haiku"}},
           "reviewers": [{"name": "qa", "kind": "claude", "agent": "qa", "model": "sonnet", "required": True}, {"name": "cross", "kind": "agy", "model": "gemini-4-argon-medium", "required": True}],
           "use": ["claude/sonnet", "claude/haiku", "agy/gemini-4-argon-medium", "codex/default"],
           "budgets": {"agy": {"tokens": 400000, "per": "day"}, "codex": {"calls": 40, "cost": 2.0, "per": "5h"}}}
    config.write_raw(p, raw)
    (h / "context" / "project.md").write_text("# Project context\n\n- What it is: A small online shop with a Python API and a plain HTML storefront.\n- Stack: Python, SQLite, plain HTML and CSS.\n"
                                              "- How to run / test / lint / build (one command each): test: python -m pytest; lint: ruff check .\n- Conventions (naming, structure, style): api/ for endpoints, web/ for pages, tests/ mirrors api/.\n"
                                              "- Things agents must never do here: edit .claude/, CLAUDE.md or GEMINI.md; deploy; commit secrets.\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial commit"], cwd=p, check=True)
    for state, rows in CARDS.items():
        for cid, title, area, attempts, goal, crit, tasks, done in rows:
            extra = "".join(f"{i}. {q}\n" + "".join(f"   {chr(97 + k)}) {o}\n" for k, o in enumerate(opts)) for i, (q, opts) in enumerate(QUESTIONS, 1)) if state == "blocked" else ""
            (h / "board" / state / f"{cid}.md").write_text(card_text(cid, title, area, attempts, goal, crit, tasks, done, extra), encoding="utf-8")
    ais = {"claude": {"installed": True, "logged_in": True, "models": ["sonnet", "opus", "haiku"]},
           "agy": {"installed": True, "logged_in": True, "models": ["gemini-4-argon-medium", "gemini-4-argon-high", "gemini-3.8-flash-high"]},
           "codex": {"installed": True, "logged_in": True, "models": ["default"], "name": "OpenAI Codex CLI"}}
    (h / "ais.json").write_text(json.dumps({"ts": "2026-11-08 09:00:00", "ais": ais}), encoding="utf-8")
    run = h / "runs" / "20261108-091200"
    run.mkdir(parents=True)
    demo_graph(p, run)
    ts = lambda m: time.strftime("%F %T", time.localtime(NOW - m * 60))  # noqa: E731
    ev = [("run_start", "-", "-", "5 card(s), base=main, 2 at a time", 0, 31), ("split", "006-dark-mode", "splitter", "single card", 4, 30), ("plan", "006-dark-mode", "frontend", "planned", 41, 30),
          ("split", "005-order-export-csv", "splitter", "single card", 3, 29), ("plan", "005-order-export-csv", "backend", "planned", 38, 29),
          ("build", "006-dark-mode", "frontend", "attempt 1: done", 212, 25), ("guardrails", "006-dark-mode", "guardrails", "PASS", 1, 21), ("ci", "006-dark-mode", "ci", "PASS", 48, 21),
          ("review", "006-dark-mode", "qa", "APPROVED", 63, 18), ("build", "005-order-export-csv", "backend", "attempt 1: done", 190, 20), ("guardrails", "005-order-export-csv", "guardrails", "PASS", 1, 15),
          ("ci", "005-order-export-csv", "ci", "FAIL: 1 failed", 52, 14), ("card_blocked", "004-refund-flow", "orchestrator", "blocked: vague or missing info, see Blockers / questions", 0, 22)]
    (run / "events.jsonl").write_text("\n".join(json.dumps({"ts": ts(m), "kind": k, "card": c, "agent": a, "result": r, "secs": s}) for k, c, a, r, s, m in ev), encoding="utf-8")
    (h / "state.json").write_text(json.dumps({"run": run.name, "ts": ts(0), "card": "006-dark-mode", "phase": "review 1",
                                                                "active": {"005-order-export-csv": "build 2/3", "006-dark-mode": "review 1"}}), encoding="utf-8")
    rows = [(5, "claude", "sonnet", "planner", 18200, 2400, 0.09), (22, "claude", "sonnet", "builder", 61000, 9800, 0.31), (26, "claude", "haiku", "splitter", 2100, 300, 0.01),
            (28, "agy", "gemini-4-argon-medium", "cross", 52000, 900, 0), (200, "agy", "gemini-4-argon-medium", "cross", 31000, 700, 0), (700, "agy", "gemini-4-argon-medium", "cross", 80000, 1500, 0),
            (8, "codex", "default", "builder", 4200, 1800, 0.0212), (4, "codex", "default", "builder", 3000, 900, 0.0132)]
    (run / "usage.jsonl").write_text("\n".join(json.dumps({"ts": NOW - m * 60, "ai": a, "model": mo, "role": r, "in": i, "out": o, "cost": c, **({"est": True} if a == "codex" else {})})
                                               for m, a, mo, r, i, o, c in rows), encoding="utf-8")
    streams = h / "streams"
    streams.mkdir(exist_ok=True)
    logs = {"pipeline": "09:12:03  006  splitter     single card (4s)\n09:12:41  006  frontend     planned (41s)\n09:16:12  006  frontend     attempt 1: done (212s)\n09:17:14  006  ci           PASS (48s)\n09:18:17  006  qa           APPROVED (63s)\n09:20:30  005  backend      attempt 1: done (190s)\n09:21:22  005  ci           FAIL: 1 failed (52s)",
            "planner": "> Read board/doing/006-dark-mode.md\n> Read web/styles.css\nThe palette is hard coded in 14 places: moving it to CSS variables is the first task.\nRESULT: PLANNED",
            "builder": "> Edit web/styles.css\n> Edit web/index.html\n> Edit web/theme.js\n> Bash python -m pytest -q\nAttempt 2: the export test expected a header row, added it.\nRESULT: DONE",
            "qa": "Reviewing card 006: dark mode for the storefront.\nThe palette uses CSS variables, the switch stores the choice, contrast checked.\nVERDICT: APPROVED",
            "cross": "Reading the review input...\nContrast of the secondary text in dark mode is 4.6:1, above the limit.", "retro": "Nothing to learn yet for this run."}
    for name, text in logs.items():
        (streams / f"{name}.log").write_text("--- run 20261108-091200 ---\n" + text + "\n", encoding="utf-8")
    claude_json = root / "claude.json"
    claude_json.write_text(json.dumps({"projects": {str(p.resolve()): {"hasTrustDialogAccepted": True}}}), encoding="utf-8")
    os.environ["LONERCHESTRATOR_CLAUDE_JSON"] = str(claude_json)
    (home / "limits.json").write_text(json.dumps({"claude": {"updated": NOW - 240, "status": "allowed", "windows": {
        "five_hour": {"utilization": 0.42, "resetsAt": NOW + 2.2 * 3600}, "seven_day": {"utilization": 0.19, "resetsAt": NOW + 3.1 * 86400}}}}), encoding="utf-8")
    trust.trust(p, config.load(p))
    usage.PROBE.update(running=False, msg="")
    return p


class FakeRunner:
    def running(self):
        return True

    def start(self):
        pass

    def stop(self):
        pass

    def message(self):
        return ""


def browser():
    found = next((e for e in EDGES if Path(e).exists()), None) or shutil.which("msedge") or shutil.which("chromium") or shutil.which("google-chrome")
    if not found:
        sys.exit("Edge or Chrome is needed to take screenshots (headless).")
    return found


def shot(exe, url, out, w, h, dark):
    profile = tempfile.mkdtemp(prefix="lc-shot-")
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", f"--user-data-dir={profile}", f"--window-size={w},{h}", "--force-device-scale-factor=1",
           f"--blink-settings=preferredColorScheme={0 if dark else 1}", "--virtual-time-budget=7000", f"--screenshot={out}", url]
    subprocess.run(cmd, check=False, capture_output=True, timeout=90)
    shutil.rmtree(profile, ignore_errors=True)
    if not Path(out).exists() or Path(out).stat().st_size < 3000:
        sys.exit(f"screenshot failed: {out}")


def xterm(n):
    if n < 16:
        return ["#000", "#c33", "#3a3", "#bb3", "#36c", "#a3a", "#3aa", "#ccc", "#777", "#f55", "#5f5", "#ff5", "#58f", "#f5f", "#5ff", "#fff"][n]
    if n >= 232:
        v = 8 + (n - 232) * 10
        return f"rgb({v},{v},{v})"
    n -= 16
    lv = [0, 95, 135, 175, 215, 255]
    return f"rgb({lv[n // 36]},{lv[n // 6 % 6]},{lv[n % 6]})"


def ansi_to_html(text):
    out, fg, bg, bold = [], None, None, False
    for part in re.split(r"(\x1b\[[0-9;]*m)", text):
        m = re.fullmatch(r"\x1b\[([0-9;]*)m", part)
        if not m:
            style = ";".join(s for s in ((f"color:{fg}" if fg else ""), (f"background:{bg}" if bg else ""), ("font-weight:700" if bold else "")) if s)
            out.append(f'<span style="{style}">{html.escape(part)}</span>' if style else html.escape(part))
            continue
        codes = [int(c or 0) for c in m.group(1).split(";")]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                fg, bg, bold = None, None, False
            elif c == 1:
                bold = True
            elif c in (38, 48) and i + 2 < len(codes) and codes[i + 1] == 5:
                if c == 38:
                    fg = xterm(codes[i + 2])
                else:
                    bg = xterm(codes[i + 2])
                i += 2
            i += 1
    return "".join(out)


def terminal_shot(exe, project, out):
    from orch import tui
    tui.COLOR = True
    screen = tui.render(project, screen=0, color=True)
    page = ("<!doctype html><meta charset=utf-8><style>html,body{margin:0;background:#0b0b0d}pre{margin:0;padding:18px 22px;color:#d4d4d8;font:14px/1.28 'Cascadia Mono',Consolas,monospace;"
            f"display:inline-block}}</style><pre>{ansi_to_html(screen)}</pre>")
    f = Path(tempfile.mkdtemp(prefix="lc-term-")) / "t.html"
    f.write_text(page, encoding="utf-8")
    shot(exe, f.as_uri(), out, 1010, 640, True)


VIEWS = [  # name, query, width, height
    ("board", "tab=Board", 1360, 520), ("flow", "tab=Flow&card=006-dark-mode", 1360, 640), ("planner", "tab=Planner", 1360, 940), ("agents", "tab=Agents", 1360, 760),
    ("ais", "tab=AIs", 1360, 1200), ("settings", "tab=Settings", 1360, 1000), ("card", "tab=Board&open=006-dark-mode", 1360, 900),
    ("new-request", "tab=Board&new=1&text=Let%20shoppers%20save%20products%20to%20a%20wishlist%20and%20get%20an%20email%20when%20one%20goes%20on%20sale", 1360, 760),
]


def main():
    """`python docs/screenshots.py` takes every view; `python docs/screenshots.py graph card` only those."""
    from orch import web
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    exe = browser()
    root = Path(tempfile.mkdtemp(prefix="lc-demo-"))
    project = build_project(root)
    httpd, url = web.serve(project, "main", 0, runner=FakeRunner())
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = url.split("?")[0]
    token = url.split("?t=")[1]
    try:
        for name, query, w, h in VIEWS + [("graph", "graph=005-order-export-csv#sel=" + DEMO["sel"], 1360, 820)]:
            if only and name not in only:
                continue
            for theme in ("light", "dark"):
                shot(exe, f"{base}?t={token}&still=1&{query}", str(OUT / f"{name}-{theme}.png"), w, h, theme == "dark")
                print("wrote", f"{name}-{theme}.png")
        if not only or "terminal" in only:
            terminal_shot(exe, project, str(OUT / "terminal.png"))
            print("wrote terminal.png")
    finally:
        httpd.shutdown()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
