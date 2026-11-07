"""Several cards at the same time. Each card works in its own git worktree (its own folder and branch), so agents never touch each other's files.

    main checkout (base branch)  <- merges and retros, ONE at a time (the lock)
    .orchestrator/worktrees/<card>  <- plan, build, guardrails, CI, review of that card

A card that finds the base branch moved by another card merges the new base into its branch and runs CI again before it is merged."""
import shutil
import subprocess
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from .agents import AuthError, RateLimitExhausted, Runner
from .board import STATES, Board, Card
from .pipeline import Pipeline, Tampered


class Hub:
    """What the card workers share: the main checkout, the lock around it, and the base branch."""

    def __init__(self, main):
        self.main, self.lock, self.project = main, threading.RLock(), Path(main.p)

    def merge(self, w, br, msg):
        with self.lock:
            base, mg, wg = w.base, self.main.git, w.git
            if mg.out("rev-parse", base).strip() != wg.out("merge-base", base, "HEAD").strip():       # another card was merged meanwhile
                if not wg.merge_base_into_current(base):
                    w.log.say("pipeline", f"   ! {br} conflicts with {base} after another card was merged")
                    return False
                ci, out = w._ci()
                if ci.returncode:
                    w.log.say("pipeline", "   ! CI fails after merging the latest " + base + "\n" + "\n".join("   | " + ln for ln in out.splitlines()[-3:]))
                    return False
            return mg.merge_no_ff(br, msg)

    def retro(self, card, status, attempts):
        """Runs in the main checkout, with the card in its final state on the main board."""
        main_card = self.send(card)
        with self.lock:
            self.main._retro(main_card, status, attempts)

    def send(self, card):
        """Copy a worker's card file to the main board in the state it is in now. Returns the main card."""
        state = card.path.parent.name
        dest = self.project / "board" / state / card.path.name
        for s in STATES:
            if s != state:
                (self.project / "board" / s / card.path.name).unlink(missing_ok=True)
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(card.path, dest)
        return Card(dest)


class Parallel:
    def __init__(self, project, cfg, log, runner, base=None, jobs=None):
        self.p, self.cfg, self.log, self.runner = Path(project), cfg, log, runner
        self.jobs = max(1, jobs or cfg.get("parallel", 1))
        self.main = Pipeline(project, cfg, log, runner, base=base)
        self.hub = Hub(self.main)
        self.stop = threading.Event()
        self.code = 0
        self.main_board = Board(project)
        self.wt_root = self.p / ".orchestrator" / "worktrees"

    def preflight(self):
        self.main.preflight()

    # ---------- the scheduler ----------
    def run(self, only=None):
        m = self.main
        m.git.checkout(m.base)
        self._exclude()

        def ready(seen):
            return [c for c in self.main_board.cards("backlog")
                    if c.id not in seen and self.main_board.ready(c) and (only is None or c.id == only or c.id.startswith(f"{only}-"))]
        seen, running = set(), {}
        todo = ready(seen)
        if not todo:
            self.log.say("pipeline", "nothing to do (backlog empty" + (f" or card '{only}' not found)" if only else ")"))
            return 0
        self.log.event("run_start", result=f"{len(todo)} card(s), base={m.base}, {self.jobs} at a time")
        with ThreadPoolExecutor(self.jobs) as ex:
            while True:
                if not self.stop.is_set():
                    for card in ready(seen):
                        if len(running) >= self.jobs:
                            break
                        seen.add(card.id)
                        with self.hub.lock:
                            card.move("doing")                      # the main board shows it right away
                        running[ex.submit(self._card, card.id)] = card.id
                if not running:
                    break
                done, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for f in done:
                    running.pop(f)
        self.log.state(card=None, phase="aborted" if self.code else "idle")
        self.log.event("run_end", result="backlog processed" if not self.code else "stopped early")
        return self.code

    # ---------- one card in its own worktree ----------
    def _card(self, cid):
        br, wt = f"card/{cid}", self.wt_root / cid
        w = None
        try:
            w = self._open(cid, br, wt)
            if w is None:
                return
            card = Card(wt / "board" / "backlog" / f"{cid}.md")
            try:
                w.process(card)
            except Tampered as e:
                self.code = 2
                self.stop.set()
                self.log.event("abort", cid, result=f"SECURITY: {e}")
                self._card_to(wt, cid, "blocked", f"BLOCKED: {e}. Inspect .git/config and .git/hooks before running again")
            except (AuthError, RateLimitExhausted) as e:
                self.code = max(self.code, 1)
                self.stop.set()
                self.log.event("abort", cid, result=str(e))
                w._park(cid, br)                       # keep the work done so far on the card branch
                self._card_to(wt, cid, "backlog", None)
            except Exception as e:                      # one broken card must not stop the others
                self.log.event("card_blocked", cid, "orchestrator", f"crashed: {type(e).__name__}: {e}")
                self._card_to(wt, cid, "blocked", f"BLOCKED: crashed ({type(e).__name__}: {e})")
        finally:
            self._finish(cid, br, wt)

    def _open(self, cid, br, wt):
        """Create the worktree + branch, copy the card into it, run the optional setup command. None when it could not be prepared."""
        mg = self.main.git
        with self.hub.lock:
            mg.run("worktree", "prune", check=False)
            if wt.exists():
                mg.run("worktree", "remove", "--force", str(wt), check=False)
                shutil.rmtree(wt, ignore_errors=True)
            wt.parent.mkdir(parents=True, exist_ok=True)
            args = ["worktree", "add", str(wt), br] if mg.has_branch(br) else ["worktree", "add", "-b", br, str(wt), self.main.base]
            r = mg.run(*args, check=False)
        src = self.p / "board" / "doing" / f"{cid}.md"
        if r.returncode:
            self.log.event("card_blocked", cid, "orchestrator", f"could not create a worktree: {r.stderr.strip()[:200]}")
            self._to_main(cid, "blocked", "BLOCKED: could not create a git worktree for this card")
            return None
        (wt / "board" / "backlog").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, wt / "board" / "backlog" / f"{cid}.md")
        if self.cfg.get("setup"):
            self.log.say("pipeline", f"{cid}: setup: {self.cfg['setup']}")
            s = subprocess.run(self.cfg["setup"], shell=True, cwd=wt, capture_output=True, text=True, encoding="utf-8", errors="replace")  # nosec B602: trusted config
            if s.returncode:
                self.log.event("card_blocked", cid, "orchestrator", "setup command failed")
                self._to_main(cid, "blocked", "BLOCKED: the `setup` command failed in the worktree:\n" + "\n".join((s.stdout + s.stderr).splitlines()[-8:]))
                return None
        runner = Runner(wt, self.cfg, self.log, usage=self.runner.usage, sleep=self.runner.sleep)
        return Pipeline(wt, self.cfg, self.log, runner, base=self.main.base, hub=self.hub)

    def _card_to(self, wt, cid, state, note):
        wcard = next((Card(p) for s in STATES for p in [wt / "board" / s / f"{cid}.md"] if p.exists()), None)
        if wcard is None:
            return
        if note:
            wcard.log(note)
        if wcard.path.parent.name != state:
            wcard.move(state)

    def _to_main(self, cid, state, note):
        with self.hub.lock:
            c = Card(self.p / "board" / "doing" / f"{cid}.md")
            if c.path.exists():
                c.log(note)
                c.move(state)

    def _finish(self, cid, br, wt):
        """Copy the card (and any child cards the splitter made) to the main board, remove the worktree, keep the branch only if it holds work."""
        try:
            wboard = Board(wt)
            with self.hub.lock:
                for s in STATES:
                    for c in wboard.cards(s):
                        if c.id == cid:
                            self.hub.send(c)
                        elif s == "backlog" and not any((self.p / "board" / t / c.path.name).exists() for t in STATES):
                            shutil.copyfile(c.path, self.p / "board" / "backlog" / c.path.name)       # a child card from the splitter
                mg = self.main.git
                if wt.exists():
                    mg.run("worktree", "remove", "--force", str(wt), check=False)
                    shutil.rmtree(wt, ignore_errors=True)
                mg.run("worktree", "prune", check=False)
                if mg.has_branch(br) and mg.ahead(self.main.base, br) == 0:
                    mg.delete_branch(br)
                else:
                    mg.run("branch", "-qd", br, check=False)         # fully merged cards: safe delete; unmerged keep their work
        finally:
            self.log.finish(cid)

    def _exclude(self):
        """The worktrees live inside the project: keep git from listing them as untracked (local, untracked file; no config change)."""
        common = self.main.git.run("rev-parse", "--git-common-dir", check=False).stdout.strip() or ".git"
        f = (self.p / common / "info" / "exclude")
        line = ".orchestrator/worktrees/"
        try:
            have = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
            if line not in have:
                f.parent.mkdir(exist_ok=True)
                f.write_text("\n".join(have + [line]) + "\n", encoding="utf-8")
        except OSError:
            pass

