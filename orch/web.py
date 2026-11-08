"""A local kanban page for the board: see every card move, add requests in plain words, answer questions, run and stop.

Standard library only. It listens on 127.0.0.1, and a random token (in the link `lonerchestrator web` prints) is required for everything, plus a
Host check against DNS rebinding and an Origin check on writes, so another web page you visit cannot drive it."""
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import answer, checks, config, intake, menu
from .board import STATES, Board, Card, create_card
from .events import STREAMS
from .safe import clean
from .view import NOW, PHASE_IDX, STAGES, _json, load_events, reviewer_status, stage_status
from .web_ais import AisApi
from .web_settings import SettingsApi
from .webcore import ANSI, ID, Bad, find_route, route

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024
ASSETS = {"/app.js": "text/javascript", "/style.css": "text/css"}


class App(AisApi, SettingsApi):
    """The API, independent of HTTP so it is easy to test. Every method returns JSON-able data or raises Bad."""

    def __init__(self, project, base, runner):
        self.project, self.base, self.runner = Path(project), base, runner
        self.board = Board(self.project)

    # ---------- reading
    def find(self, cid):
        if not ID.match(cid or ""):
            raise Bad("bad card id")
        for s in STATES:
            p = self.board.root / s / f"{cid}.md"
            if p.is_file():
                return Card(p)
        raise Bad("no such card", 404)

    def summary(self, c, active):
        tasks = re.findall(r"^- \[( |x|X)\] ", c.section("Tasks"), re.MULTILINE)
        return {"id": c.id, "title": c.title, "area": c.area, "attempts": c.get("attempts", "0"), "depends": c.get("depends"),
                "tasks": len(tasks), "done": sum(t != " " for t in tasks), "questions": len(answer.parse(c)) if c.path.parent.name == "blocked" else 0,
                "phase": active.get(c.id, ""), "moves": self.moves(c, active)}

    @route("GET", "/api/state")
    def state(self):
        active, _ = self.active()
        cfg = config.load(self.project)
        ais = _json(self.project / ".orchestrator" / "ais.json").get("ais", {})
        cols = {s: [self.summary(c, active) for c in self.board.cards(s)] for s in STATES}
        bad = [t for s, t, _ in checks.readiness(self.project) if s == "fail"]
        return {"project": self.project.name, "base": self.base, "columns": cols, "running": self.runner.running(), "run_msg": self.runner.message(),
                "roles": {r: menu.assigned(cfg, r) for r in menu.SLOTS},
                "pills": [{"id": k, "ok": bool(v.get("logged_in"))} for k, v in ais.items() if v.get("installed") or k in ("claude", "agy")], "parallel": cfg.get("parallel", 1), "builders": cfg.get("builders", 1), "problems": bad}

    @route("GET", "/api/card/", takes="tail")
    def card(self, cid):
        c = self.find(cid)
        qs = answer.parse(c) if c.path.parent.name == "blocked" else []
        active, _ = self.active()
        _, ev = load_events(self.project)
        tasks = [{"text": t, "done": d != " "} for d, t in re.findall(r"^- \[( |x|X)\] (.+)$", c.section("Tasks"), re.MULTILINE)]
        crit = [{"text": t, "done": d != " "} for d, t in re.findall(r"^- \[( |x|X)\] (.+)$", c.section("Acceptance criteria"), re.MULTILINE)]
        log = c.section("Status log").splitlines()[-25:]
        return {**self.summary(c, active), "state": c.path.parent.name, "goal": c.section("Goal"), "criteria": crit, "plan": c.section("Plan"), "tasks": tasks,
                "out_of_scope": c.section("Out of scope"), "answers": c.section("Answers"), "log": log,
                "questions": [{"text": q.text, "options": q.options} for q in qs],
                "events": [{k: e.get(k, "") for k in ("ts", "kind", "agent", "result")} for e in ev if e.get("card") == cid][-30:]}

    def active(self):
        st, _ = load_events(self.project)
        return st.get("active") or ({st["card"]: st.get("phase", "")} if st.get("card") else {}), st

    def moves(self, c, active):
        """Where the user may drag this card. The pipeline alone moves cards into doing/review/done."""
        s = c.path.parent.name
        if c.id in active or (s in ("doing", "review") and self.runner.running()):
            return []
        return {"backlog": ["blocked"], "blocked": ["backlog"], "done": ["backlog"], "doing": ["backlog", "blocked"], "review": ["backlog", "blocked"]}[s]

    @route("POST", "/api/move", takes="body")
    def move(self, body):
        c, to = self.find(body.get("id")), body.get("to")
        active, _ = self.active()
        if to in ("doing", "review", "done"):
            raise Bad("only the pipeline moves a card there")
        if to not in self.moves(c, active):
            raise Bad("that card cannot go there now" + (" (it is being worked on)" if c.id in active else ""), 409)
        c.set("attempts", 0)
        c.log(f"moved to {to} by the user (web page)")
        c.move(to)
        return {"id": c.id, "to": to, "unanswered": bool(to == "backlog" and answer.parse(c))}

    @route("POST", "/api/reorder", takes="body")
    def reorder(self, body):
        ids = body.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise Bad("send the backlog ids in the new order")
        have = {c.id for c in self.board.cards("backlog")}
        if set(ids) != have:
            raise Bad("the backlog changed, refresh and try again", 409)
        for n, cid in enumerate(ids, 1):
            Card(self.board.root / "backlog" / f"{cid}.md").set("priority", n * 10)
        return {"ok": True}

    # ---------- the other tabs of the terminal panel
    @route("GET", "/api/flow", takes="card")
    def flow(self, cid=None):
        active, st = self.active()
        _, ev = load_events(self.project)
        cfg = config.load(self.project)
        recent = list(dict.fromkeys(list(active) + [e["card"] for e in reversed(ev) if e["card"] != "-"]))[:12]
        cid = cid if cid in recent else (next(iter(active), None) or (recent[0] if recent else None))
        evs = [e for e in ev if e["card"] == cid] if cid else []
        phase = active.get(cid, "") if cid else ""
        cur = PHASE_IDX.get(phase.split()[0]) if phase else None
        stages = stage_status(evs, cur)
        revs, got = reviewer_status(evs, cur, [r["name"] for r in cfg["reviewers"]])
        title = self.find(cid).title if cid and ID.match(cid) and any((self.board.root / s / f"{cid}.md").is_file() for s in STATES) else ""
        now = NOW.get(phase.split()[0], phase) if phase else ("idle" if not self.runner.running() else "waiting for the next card")
        return {"card": cid, "title": title, "phase": phase, "now": now, "cards": recent,
                "stages": [{"name": n, "status": s} for n, s in zip(STAGES, stages, strict=True)],
                "reviewers": [{"name": n, "status": s, "verdict": got.get(n, "")} for n, s in revs.items()],
                "events": [{k: e.get(k, "") for k in ("ts", "kind", "agent", "result", "secs")} for e in evs[-40:]], "attempts": f"{phase.split()[1]}" if " " in phase else ""}

    @route("GET", "/api/agents")
    def agents(self):
        active, _ = self.active()
        phases = {p.split()[0] for p in active.values() if p}
        live = {"planner": bool(phases & {"split", "plan"}), "builder": "build" in phases, "qa": "review" in phases, "cross": "review" in phases, "retro": "retro" in phases,
                "pipeline": bool(phases)}
        out = []
        for name in STREAMS:
            f = self.project / ".orchestrator" / "streams" / f"{name}.log"
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
            except OSError:
                lines = []
            out.append({"name": name, "live": live.get(name, False), "lines": [clean(ANSI.sub("", ln))[:400] for ln in lines if ln.strip() and not ln.startswith("--- run")][-40:]})
        return {"agents": out}

    # ---------- writing
    @route("POST", "/api/new", takes="body")
    def new(self, body):
        text = " ".join(str(body.get("text", "")).split())
        if len(text) < 3:
            raise Bad("write what you want changed")
        draft = intake.analyze(self.project, text, use_ai=bool(body.get("ai", True)))
        area = body.get("area") if body.get("area") in ("frontend", "backend", "both") else draft["area"]
        path = create_card(self.project, draft["title"], area, goal=draft["goal"], criteria=draft["criteria"])
        if body.get("run", True):
            self.runner.start()
        return {"id": path.stem, "draft": {**draft, "area": area}, "started": bool(body.get("run", True))}

    @route("POST", "/api/answer", takes="body")
    def answer(self, body):
        c = self.find(body.get("id"))
        if c.path.parent.name != "blocked":
            raise Bad("that card is not waiting for answers")
        qs, given = answer.parse(c), body.get("answers")
        if not isinstance(given, list) or len(given) != len(qs):
            raise Bad(f"send {len(qs)} answers (empty to skip)")
        texts = [answer.pick(q, str(a)[:2000]) for q, a in zip(qs, given, strict=True)]
        if not answer.apply(c, qs, texts):
            raise Bad("every answer was empty")
        if body.get("run", True):
            self.runner.start()
        return {"id": c.id, "queued": True}

    @route("POST", "/api/suggest", takes="body")
    def suggest(self, body):
        c = self.find(body.get("id"))
        return {"added": answer.add_suggestions(c), **{"questions": [{"text": q.text, "options": q.options} for q in answer.parse(c)]}}

    @route("POST", "/api/requeue", takes="body")
    def requeue(self, body):
        c = self.find(body.get("id"))
        if c.path.parent.name != "blocked":
            raise Bad("only blocked cards can be sent back")
        c.set("attempts", 0)
        c.log("sent back to the backlog from the web page")
        c.move("backlog")
        return {"id": c.id}

    @route("POST", "/api/run")
    def run(self):
        self.runner.start()
        return {"running": True}

    @route("POST", "/api/stop")
    def stop(self):
        self.runner.stop()
        return {"running": False}

    # ---------- routing
    def dispatch(self, method, path, body, query=None):
        found = find_route(method, path)
        if found is None:
            raise Bad("not found", 404)
        name, takes, tail = found
        args = {None: (), "body": (body,), "card": ((query or {}).get("card"),), "tail": (tail,)}[takes]
        return getattr(self, name)(*args)


class ProcRunner:
    """Starts/stops `lonerchestrator run` as a background process (the same one the terminal panel uses)."""

    def __init__(self, project, base):
        from .tui import Runner
        self.r = Runner(project, base)

    def running(self):
        return bool(self.r.proc and self.r.proc.poll() is None)

    def start(self):
        self.r.start()

    def stop(self):
        self.r.stop()

    def message(self):
        p = self.r.proc
        return "" if not p else "running" if p.poll() is None else "finished" if p.returncode == 0 else f"stopped (code {p.returncode})"


def make_handler(app, token, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "lonerchestrator"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _guard(self, write):
            if self.headers.get("Host") not in hosts:
                raise Bad("bad host", 403)                      # DNS rebinding
            if write:
                origin = self.headers.get("Origin")
                if origin and origin.split("://", 1)[-1] not in hosts:
                    raise Bad("bad origin", 403)

        def _go(self, method):
            try:
                url = urlparse(self.path)
                self._guard(method == "POST")
                if method == "GET" and url.path == "/":
                    if not secrets.compare_digest(parse_qs(url.query).get("t", [""])[0], token):
                        raise Bad("open the link that `lonerchestrator web` printed (it contains the access token)", 403)
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
                if method == "GET" and url.path in ASSETS:                    # the page's own script and style: nothing secret in them
                    return self._send(200, (STATIC / url.path[1:]).read_bytes(), ASSETS[url.path])
                if not secrets.compare_digest(self.headers.get("X-Token", ""), token):
                    raise Bad("missing or wrong token", 403)
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > MAX_BODY:
                        raise Bad("request too large", 413)
                    try:
                        body = json.loads(self.rfile.read(n) or b"{}")
                    except ValueError:
                        raise Bad("bad JSON") from None
                    if not isinstance(body, dict):
                        raise Bad("bad JSON")
                self._send(200, app.dispatch(method, url.path, body, {k: v[0] for k, v in parse_qs(url.query).items()}))
            except Bad as e:
                self._send(e.code, {"error": str(e)})
            except Exception as e:                              # noqa: BLE001  (never leak a traceback to the page)
                self._send(500, {"error": f"{type(e).__name__}: {e}"[:200]})

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

    return H


def serve(project, base, port=0, runner=None):
    """(httpd, url). Call httpd.serve_forever(); the URL carries the access token."""
    token = secrets.token_urlsafe(24)
    app = App(project, base, runner or ProcRunner(project, base))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), lambda *a: None)
    httpd.RequestHandlerClass = make_handler(app, token, httpd.server_address[1])
    httpd.app, httpd.token = app, token
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/?t={token}"


def run_web(project, base, port=0, open_browser=True):
    import webbrowser
    httpd, url = serve(project, base, port)
    print(f"\nlonerchestrator board for {Path(project).name}:\n\n    {url}\n\n(only this computer can open it; Ctrl+C stops it)", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
