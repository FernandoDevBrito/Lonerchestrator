"""The loop: validate -> plan(+tasks) -> build -> guardrails -> CI -> independent review -> merge -> retro."""
import contextlib
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import ai, answer, groups, guardrails, menu, term
from .agents import AuthError, RateLimitExhausted, marker, verdict
from .board import Board
from .gitops import Git


class Tampered(Exception):
    """An agent changed .git/config or a git hook: anything git runs from now on could execute attacker-chosen code."""


class _Guarded:
    """Wraps the agent runner: .git/config and hooks must be identical before and after every agent call."""

    def __init__(self, runner, git):
        self.runner, self.git = runner, git

    def _call(self, fn, *a, **kw):
        before = self.git.internals()
        out = fn(*a, **kw)
        if self.git.internals() != before:
            raise Tampered("an agent changed .git/config or a git hook")
        return out

    def claude(self, *a, **kw):
        return self._call(self.runner.claude, *a, **kw)

    def agy(self, *a, **kw):
        return self._call(self.runner.agy, *a, **kw)

    def provider(self, *a, **kw):
        return self._call(self.runner.provider, *a, **kw)


class Pipeline:
    def __init__(self, project, cfg, log, runner, base=None, hub=None):
        self.hub = hub                      # set when this pipeline works in its own git worktree (parallel cards): see parallel.py
        self.p, self.cfg, self.log = project, cfg, log
        self.base = base or cfg["base"]
        self.git, self.board = Git(project, hooks=cfg.get("git_hooks", False)), Board(project)
        self.run_ = _Guarded(runner, self.git)

    def _m(self, role):
        return self.cfg["roles"][role].get("model")

    def _instructions(self, agent):
        """Claude Code has its own agents (.claude/agents/<name>.md). Every other AI gets the same role text, plus the project rules, in the prompt."""
        def body(path):
            t = path.read_text(encoding="utf-8") if path.is_file() else ""
            return t.split("---", 2)[2].strip() if t.startswith("---") and t.count("---") >= 2 else t.strip()
        agent_md, rules = body(self.p / ".claude" / "agents" / f"{agent}.md"), body(self.p / "CLAUDE.md")[:8000]
        return f"# Your role: {agent}\n{agent_md}\n\n# Project rules (CLAUDE.md)\n{rules}\n\n# Your task\n"

    def _ai(self, pid):
        found = ai.registry(self.cfg).get(pid)
        if found is None:
            raise ValueError(f"'{pid}' is not a defined AI (see `providers` in .orchestrator/config.json)")
        return found

    def _ask(self, role, agent, prompt, mode="edit"):
        """Run one role on whichever AI the config gives it: how that AI is called is its own business (see ai.py)."""
        spec = self.cfg["roles"][role]
        return self._ai(spec.get("cli", "claude")).call(self.run_, role, agent, spec.get("model"), prompt, mode, self._instructions)

    # ---------- run ----------
    def preflight(self):
        if not self.git.has_branch(self.base):
            raise SystemExit(f"base branch '{self.base}' not found")
        bad = menu.problems(self.cfg)
        if bad:
            raise SystemExit("; ".join(bad) + ". Open the AIs tab (key 5) in `lonerchestrator` to fix it.")
        reg = ai.registry(self.cfg)
        used = [(role, self.cfg["roles"][role], True) for role in ("planner", "builder", "retro") + (("splitter",) if self.cfg["split"] else ())]
        used += [(r["name"], {"cli": r["kind"], "model": r.get("model")}, r.get("required", True)) for r in self.cfg["reviewers"]]
        for label, s, required in used:
            who = reg.get(s.get("cli", "claude"))
            if who is None:
                raise SystemExit(f"{label} uses an AI called '{s.get('cli')}' that is not defined. Pick another in the AIs tab or define it under `providers` in .orchestrator/config.json")
            if label in ("planner", "builder", "retro", "splitter") and not who.can_edit:
                raise SystemExit(f"{label} uses {who.name}, which cannot edit files. Give that role an AI that can (AIs tab), keep {who.name} for reviewing")
            if required and not who.installed():
                raise SystemExit(f"{label} needs {who.name} ('{who.spec['exe']}' is not installed). Run `lonerchestrator ais` to install it, or pick another AI for {label} in the AIs tab")

    def run(self, only=None):
        self.git.checkout(self.base)
        def pending(seen):
            return [c for c in self.board.cards("backlog") if c.id not in seen and self.board.ready(c) and (only is None or c.id == only or c.id.startswith(f"{only}-"))]

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
            except Tampered as e:                       # no git command may run after this: only plain file operations
                self.log.event("abort", card.id, result=f"SECURITY: {e}")
                self.log.state(card=None, phase="aborted")
                card.move("blocked")
                card.log(f"BLOCKED: {e}. Inspect .git/config and .git/hooks before running again")
                return 2
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
        out = self._ask("planner", agent, f"PHASE=PLAN. Card: {card.path.as_posix()}. Follow your agent instructions and CLAUDE.md.")
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
            out = self._team(card, agent, n, feedback) if n == 1 else None
            if out is None:
                out = self._ask("builder", agent, f"PHASE=IMPLEMENT, attempt {n} of {g['max_attempts']}. "
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
            ci, ci_out = self._ci()
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

    def _team(self, card, agent, n, feedback):
        """Several builders on one card: the plan's tasks are grouped by the files they declare, each group is built in its own throw-away
        worktree, and the parts are merged into the card branch. Returns the build output, or None to let ONE builder do the card
        (no groups, a part that touches other files, a blocked part, or any merge conflict: nothing is kept)."""
        parts = groups.split(card.section("Tasks"), self.cfg.get("builders", 1))
        if not parts or not hasattr(self.run_.runner, "at"):
            return None
        cid, head, made = card.id, self.git.out("rev-parse", "HEAD").strip(), []
        lock = self.hub.lock if self.hub else contextlib.nullcontext()
        try:
            with lock:
                for i in range(1, len(parts) + 1):
                    d, br = Path(tempfile.mkdtemp(prefix="lc-part-")), f"part/{cid}-{i}"
                    self.git.run("branch", "-D", br, check=False)
                    self.git.run("worktree", "add", "-b", br, str(d), head)
                    made.append((br, d))
                    (d / "board" / "doing").mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(card.path, d / "board" / "doing" / card.path.name)

            def build(i):
                br, d = made[i]
                tasks, files = parts[i]
                sub = Pipeline(d, self.cfg, self.log, self.run_.runner.at(d), base=self.base)
                mine = (d / "board" / "doing" / card.path.name).as_posix()
                out = sub._ask("builder", agent, f"PHASE=IMPLEMENT, attempt {n} of {self.cfg['max_attempts']}. PART {i + 1} of {len(parts)}: you are one of "
                               f"{len(parts)} builders working at the same time on separate parts of this card. Card: {mine}. "
                               f"Feedback (empty on the first attempt): {feedback.as_posix()}\nDo ONLY these tasks:\n" + "\n".join(f"- [ ] {t}" for t in tasks) +
                               f"\nChange ONLY these files: {', '.join(files)}. Do not touch any other file and do not run git.")
                self.log.artifact(cid, f"build{n}-part{i + 1}.txt", out)
                sub.git.add_all()
                bad = [f for f in sub.git.changed(head) if f not in files]
                if marker(out) == "BLOCKED" or bad:
                    return f"part {i + 1}: " + ("blocked" if marker(out) == "BLOCKED" else "touched other files: " + ", ".join(bad[:5]))
                if sub.git.changed(head):
                    sub.git.commit(f"part {i + 1} of card {cid}")
                return None
            with ThreadPoolExecutor(len(parts)) as ex:
                problems = [p for p in ex.map(build, range(len(parts))) if p]
            if not problems:
                for br, _ in made:
                    if self.git.run("merge", "-q", "--no-edit", br, check=False).returncode:
                        self.git.run("merge", "--abort", check=False)
                        problems.append(f"{br} conflicts")
                        break
            if problems:
                self.git.run("reset", "--hard", head, check=False)
                self.log.say("pipeline", f"   team build dropped ({'; '.join(problems)}): one builder does the card")
                card.log(f"attempt {n}: team build dropped ({'; '.join(problems)})")
                return None
            self.log.say("pipeline", f"   {len(parts)} builders worked on {cid} together")
            return f"RESULT: DONE\nbuilt by {len(parts)} builders"
        finally:
            with lock:
                for br, d in made:
                    self.git.run("worktree", "remove", "--force", str(d), check=False)
                    shutil.rmtree(d, ignore_errors=True)
                    self.git.run("branch", "-D", br, check=False)

    def _ci(self):
        ci = subprocess.run(term.fix_ci_command(self.cfg["ci"]), shell=True,  # nosec B602: the command comes from the project config the user approved (trust.py)
                            cwd=self.p, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return ci, ci.stdout + ci.stderr

    def _split(self, card, br, t0, agent):
        """Splitter agent: big card -> child cards in backlog. Returns True when the parent card was handled here."""
        cid, t = card.id, time.time()
        before = {c.id for c in self.board.cards("backlog")}
        self.log.state(card=cid, phase="split")
        out = self._ask("splitter", "splitter", f"Split-or-keep decision for card {card.path.as_posix()}.")
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
        known = ai.registry(self.cfg)

        def one(r):
            who = known.get(r["kind"])
            if who is None or (not who.native and not r.get("required", True) and not who.installed()):
                return r["name"], ("APPROVED", f"skipped: {r['kind']} not installed")
            o = who.review(self.run_, r["name"], r.get("agent", "qa"), r.get("model"), cid, review, self._instructions)
            return r["name"], (verdict(o), o)
        with ThreadPoolExecutor(len(self.cfg["reviewers"])) as ex:
            return dict(ex.map(one, self.cfg["reviewers"]))

    # ---------- outcomes ----------
    def _approve(self, card, br, t0, n):
        cid = card.id
        self.log.state(card=cid, phase="merge")
        self.git.add_all()
        if self.git.run("diff", "--cached", "--quiet", check=False).returncode:      # the parts of a team build are already committed
            self.git.commit(f"card {cid}: {card.title}", f"Approved by {', '.join(r['name'] for r in self.cfg['reviewers'])} after {n} attempt(s); CI green.")
        if not self._merge(br, f"Merge card {cid}: {card.title}"):
            return self._block(card, br, t0, f"merge into {self.base} failed")
        card.log(f"APPROVED after {n} attempt(s), merged into {self.base}")
        card.move("done")
        self.log.event("card_done", cid, "orchestrator", f"merged into {self.base}", time.time() - t0, attempts=n)
        self._retro(card, "done", n)

    def _merge(self, br, msg):
        if self.hub:                                  # parallel: the shared main checkout does the merge, one card at a time
            return self.hub.merge(self, br, msg)
        self.git.checkout(self.base)
        if not self.git.merge_no_ff(br, msg):
            return False
        self.git.delete_branch(br)   # fully merged, safe delete
        return True

    def _block(self, card, br, t0, reason):
        card.log(f"BLOCKED: {reason}")
        if answer.missing_options(card):
            card.log("note: some questions have no 3 suggested answers (a/b/c): the agent ignored the format, you can still type your own")
        card.move("blocked")
        self._park(card.id, br)
        self.log.event("card_blocked", card.id, "orchestrator", f"blocked: {reason}", time.time() - t0)
        self._retro(card, "blocked", int(card.get("attempts", "0") or 0))

    def _park(self, cid, br):
        """Keep work-in-progress on the card branch and return to base."""
        self.git.commit_if_dirty(f"WIP card {cid} (parked)")
        if self.hub:                                  # the worktree is removed afterwards; the branch keeps the work
            return
        self.git.checkout(self.base)
        if self.git.has_branch(br) and self.git.ahead(self.base, br) == 0:
            self.git.delete_branch(br)

    def _retro(self, card, status, attempts):
        if self.hub:                                  # retro writes memory/context in the main checkout: one at a time
            return self.hub.retro(card, status, attempts)
        self.log.state(card=card.id, phase="retro")
        t = time.time()
        self._ask("retro", "retro", f"Run the retrospective for card {card.path.as_posix()} (status: {status}).")
        self.log.event("retro", card.id, "retro", "ok", time.time() - t)
        hist = self.p / "context" / "history.md"
        hist.parent.mkdir(exist_ok=True)
        with hist.open("a", encoding="utf-8") as f:
            f.write(f"- {time.strftime('%F')} `{card.id}` {card.title}: {status}, {attempts} attempt(s)\n")
        self.git.run("add", "memory", "context", check=False)
        if self.git.run("diff", "--cached", "--quiet", check=False).returncode:
            self.git.commit(f"retro: lessons from card {card.id}")
