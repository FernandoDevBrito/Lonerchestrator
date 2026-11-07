"""The loop: validate -> plan(+tasks) -> build -> guardrails -> CI -> independent review -> merge -> retro."""
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from . import guardrails
from .agents import AuthError, RateLimitExhausted, marker, verdict
from .board import Board
from .gitops import Git


class Pipeline:
    def __init__(self, project, cfg, log, runner, base=None):
        self.p, self.cfg, self.log, self.run_ = project, cfg, log, runner
        self.base = base or cfg["base"]
        self.git, self.board = Git(project), Board(project)

    def _m(self, role):
        return self.cfg["roles"][role].get("model")

    # ---------- run ----------
    def preflight(self):
        if not self.git.has_branch(self.base):
            raise SystemExit(f"base branch '{self.base}' not found")
        for r in self.cfg["reviewers"]:
            exe = {"claude": "claude", "agy": "agy"}[r["kind"]]
            if r.get("required", True) and not shutil.which(exe):
                raise SystemExit(f"reviewer '{r['name']}' needs the '{exe}' CLI (or set required=false in config)")
        if not shutil.which("claude"):
            raise SystemExit("claude CLI not found")

    def run(self, only=None):
        self.git.checkout(self.base)
        def pending(seen):
            return [c for c in self.board.cards("backlog") if c.id not in seen and (only is None or c.id == only or c.id.startswith(f"{only}-"))]

        seen, todo = set(), pending(set())
        if not todo:
            self.log.say("pipeline", "nothing to do (backlog empty" + (f" or card '{only}' not found)" if only else ")"))
            return 0
        self.log.event("run_start", result=f"{len(todo)} card(s), base={self.base}")
        while todo:
            card = todo[0]
            seen.add(card.id)
            try:
                self.process(card)
            except (AuthError, RateLimitExhausted) as e:
                card.move("backlog")
                self._park(card.id, f"card/{card.id}")
                self.log.event("abort", card.id, result=str(e))
                self.log.state(card=None, phase="aborted")
                return 1
            todo = pending(seen)
        self.log.state(card=None, phase="idle")
        self.log.event("run_end", result="backlog processed")
        return 0

    # ---------- one card ----------
    def process(self, card):
        t0, cid, br = time.time(), card.id, f"card/{card.id}"
        area, g = card.area, self.cfg
        agent = g["agents"].get(area, "backend")
        bad = card.problems()
        if bad:
            return self._block(card, br, t0, "invalid card: " + "; ".join(bad))
        if g["split"] and self._split(card, br, t0, agent):
            return
        card.move("doing")
        card.set("attempts", 0)
        if self.git.has_branch(br):
            self.git.checkout(br)
            if not self.git.merge_base_into_current(self.base):
                return self._block(card, br, t0, f"{br} conflicts with {self.base}")
        else:
            self.git.checkout(br, create_from=self.base)
        card.log(f"started on {br} (base {self.base})")

        # PLAN (+ tasks): the planner never changes code; vague cards stop here
        self.log.state(card=cid, phase="plan")
        t = time.time()
        out = self.run_.claude("planner", agent, model=self._m("planner"), prompt=f"PHASE=PLAN. Card: {card.path.as_posix()}. Follow your agent instructions and CLAUDE.md.")
        self.log.artifact(cid, "plan.txt", out)
        m = marker(out)
        if m == "BLOCKED":
            self.log.event("plan", cid, agent, "blocked: questions in card", time.time() - t)
            return self._block(card, br, t0, "vague or missing info, see Blockers / questions")
        if m != "PLANNED" or not re.search(r"^- \[ \]", card.section("Tasks"), re.MULTILINE):
            self.log.event("plan", cid, agent, "invalid plan", time.time() - t)
            return self._block(card, br, t0, "planner did not produce a RESULT marker and a ## Tasks checklist")
        self.log.event("plan", cid, agent, "planned", time.time() - t)

        feedback = self.log.artifact(cid, "feedback.txt", "")
        for n in range(1, g["max_attempts"] + 1):
            if time.time() - t0 > g["card_timeout_min"] * 60:
                return self._block(card, br, t0, f"timeout > {g['card_timeout_min']} min")
            card.set("attempts", n)
            # BUILD
            self.log.state(card=cid, phase=f"build {n}/{g['max_attempts']}")
            t = time.time()
            out = self.run_.claude("builder", agent, model=self._m("builder"), prompt=f"PHASE=IMPLEMENT, attempt {n} of {g['max_attempts']}. "
                                   f"Card: {card.path.as_posix()}. Feedback from the previous attempt (empty on the first): {feedback.as_posix()}")
            self.log.artifact(cid, f"build{n}.txt", out)
            if marker(out) == "BLOCKED":
                self.log.event("build", cid, agent, f"attempt {n}: blocked", time.time() - t)
                return self._block(card, br, t0, "builder found missing info, see Blockers / questions")
            self.log.event("build", cid, agent, f"attempt {n}: done", time.time() - t)

            # GUARDRAILS
            self.log.state(card=cid, phase=f"guardrails {n}")
            self.git.add_all()
            diff = self.git.diff_cached(self.base)
            viol = guardrails.check_diff(g["guardrails"], self.git.changed(self.base), self.git.changed(self.base, deleted=True), diff)
            if viol:
                self.log.event("guardrails", cid, "guardrails", f"attempt {n}: {len(viol)} violation(s)")
                for v in viol:
                    self.log.say("pipeline", f"   ! {v}")
                card.log(f"attempt {n}: guardrails: " + "; ".join(viol))
                feedback = self.log.artifact(cid, "feedback.txt", "GUARDRAIL VIOLATIONS. Fix these:\n- " + "\n- ".join(viol))
                continue

            # CI
            self.log.state(card=cid, phase=f"ci {n}")
            t = time.time()
            ci = subprocess.run(g["ci"], shell=True, cwd=self.p, capture_output=True, text=True, encoding="utf-8", errors="replace")
            ci_out = ci.stdout + ci.stderr
            self.log.artifact(cid, f"ci{n}.txt", ci_out)
            self.log.say("pipeline", "\n".join("   | " + ln for ln in ci_out.splitlines()[-2:]))
            if ci.returncode:
                self.log.event("ci", cid, "ci", f"attempt {n}: FAIL", time.time() - t)
                card.log(f"attempt {n}: CI failed")
                feedback = self.log.artifact(cid, "feedback.txt", "CI FAILED. Fix these:\n" + "\n".join(ci_out.splitlines()[-80:]))
                continue
            self.log.event("ci", cid, "ci", "PASS", time.time() - t)

            # REVIEW: independent reviewers, in parallel
            self.log.state(card=cid, phase=f"review {n}")
            review = self.log.artifact(cid, f"review{n}.txt", "# CARD\n" + card.for_review() + "\n\n# DIFF\n" + diff +
                                       "\n\n# CI OUTPUT (tail)\n" + "\n".join(ci_out.splitlines()[-60:]))
            results = self._review(cid, review)
            for name, (v, _) in results.items():
                self.log.event("review", cid, name, v)
            if all(v == "APPROVED" for v, _ in results.values()):
                return self._approve(card, br, t0, n)
            summary = ", ".join(f"{k}={v}" for k, (v, _) in results.items())
            card.log(f"attempt {n} rejected ({summary})")
            feedback = self.log.artifact(cid, "feedback.txt", "REVIEW REJECTED. Fix these failures.\n" +
                                         "\n".join(f"## {k}\n{o}" for k, (_, o) in results.items()))
        self._block(card, br, t0, f"needs human: {g['max_attempts']} attempts exhausted")

    def _split(self, card, br, t0, agent):
        """Splitter agent: big card -> child cards in backlog. Returns True when the parent card was handled here."""
        cid, t = card.id, time.time()
        before = {c.id for c in self.board.cards("backlog")}
        self.log.state(card=cid, phase="split")
        out = self.run_.claude("splitter", "splitter", model=self._m("splitter"), prompt=f"Split-or-keep decision for card {card.path.as_posix()}.")
        self.log.artifact(cid, "split.txt", out)
        m = marker(out)
        kids = [c for c in self.board.cards("backlog") if c.id not in before]
        if m == "BLOCKED":
            self.log.event("split", cid, "splitter", "blocked: questions in card", time.time() - t)
            self._block(card, br, t0, "vague or missing info, see Blockers / questions")
            return True
        if m == "SPLIT":
            bad = [f"{k.id}: {'; '.join(k.problems())}" for k in kids if k.problems()]
            if len(kids) < 2 or bad:
                for k in kids:
                    k.path.unlink()
                self.log.event("split", cid, "splitter", "invalid split, keeping card whole", time.time() - t)
                return False
            card.log(f"split into {len(kids)} cards: " + ", ".join(k.id for k in kids))
            card.move("done")
            self.log.event("split", cid, "splitter", f"split into {len(kids)} cards", time.time() - t)
            self.log.event("card_done", cid, "orchestrator", "split (children queued)", time.time() - t0)
            return True
        self.log.event("split", cid, "splitter", "single card", time.time() - t)
        return False

    def _review(self, cid, review):
        card_note = f"Review input (card without plan/log, diff, CI tail): {review.as_posix()}."
        def one(r):
            if r["kind"] == "claude":
                o = self.run_.claude(r["name"], r["agent"], f"Evaluate card {cid}. {card_note} Follow your agent instructions.", model=r.get("model"))
            else:
                if not r.get("required", True) and not shutil.which("agy"):
                    return r["name"], ("APPROVED", "skipped: agy not installed")
                o = self.run_.agy(r["name"], r["model"], f"Read GEMINI.md, then read {review.as_posix()} and review it exactly as GEMINI.md says. Do not run commands or edit files.")
            return r["name"], (verdict(o), o)
        with ThreadPoolExecutor(len(self.cfg["reviewers"])) as ex:
            return dict(ex.map(one, self.cfg["reviewers"]))

    # ---------- outcomes ----------
    def _approve(self, card, br, t0, n):
        cid = card.id
        self.log.state(card=cid, phase="merge")
        self.git.commit(f"card {cid}: {card.title}", f"Approved by {', '.join(r['name'] for r in self.cfg['reviewers'])} after {n} attempt(s); CI green.")
        self.git.checkout(self.base)
        if not self.git.merge_no_ff(br, f"Merge card {cid}: {card.title}"):
            return self._block(card, br, t0, f"merge into {self.base} failed")
        self.git.delete_branch(br)   # fully merged, safe delete
        card.log(f"APPROVED after {n} attempt(s), merged into {self.base}")
        card.move("done")
        self.log.event("card_done", cid, "orchestrator", f"merged into {self.base}", time.time() - t0, attempts=n)
        self._retro(card, "done", n)

    def _block(self, card, br, t0, reason):
        card.log(f"BLOCKED: {reason}")
        card.move("blocked")
        self._park(card.id, br)
        self.log.event("card_blocked", card.id, "orchestrator", f"blocked: {reason}", time.time() - t0)
        self._retro(card, "blocked", int(card.get("attempts", "0") or 0))

    def _park(self, cid, br):
        """Keep work-in-progress on the card branch and return to base."""
        self.git.commit_if_dirty(f"WIP card {cid} (parked)")
        self.git.checkout(self.base)
        if self.git.has_branch(br) and self.git.ahead(self.base, br) == 0:
            self.git.delete_branch(br)

    def _retro(self, card, status, attempts):
        self.log.state(card=card.id, phase="retro")
        t = time.time()
        self.run_.claude("retro", "retro", model=self._m("retro"), prompt=f"Run the retrospective for card {card.path.as_posix()} (status: {status}).")
        self.log.event("retro", card.id, "retro", "ok", time.time() - t)
        hist = self.p / "context" / "history.md"
        hist.parent.mkdir(exist_ok=True)
        with hist.open("a", encoding="utf-8") as f:
            f.write(f"- {time.strftime('%F')} `{card.id}` {card.title}: {status}, {attempts} attempt(s)\n")
        self.git.run("add", "memory", "context", check=False)
        if self.git.run("diff", "--cached", "--quiet", check=False).returncode:
            self.git.commit(f"retro: lessons from card {card.id}")
