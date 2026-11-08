"""The steps a card goes through, one small object each. A stage looks at the job and answers with an Outcome:

    PASS          go on to the next stage
    retry(text)   this attempt failed: `text` becomes the builder's feedback, start the next attempt
    block(why)    stop, the card goes to blocked/ with that reason
    APPROVED      every reviewer said yes: merge it

Pipeline.process only runs Plan once, then the attempt stages (Build, Guardrails, CI, Review) in order until one blocks, one approves or the
attempts run out. To add a step (a security scan, a second CI) write a class with `run(p, job)` and put it in Pipeline.stages."""
import re
import time
from collections import namedtuple

from . import guardrails
from .agents import marker

Outcome = namedtuple("Outcome", "kind text")
PASS = Outcome("pass", "")
APPROVED = Outcome("approved", "")


def retry(text):
    return Outcome("retry", text)


def block(reason):
    return Outcome("block", reason)


class Job:
    """What the stages share about one card while it is being worked on."""

    def __init__(self, card, br, t0, agent):
        self.card, self.br, self.t0, self.agent = card, br, t0, agent
        self.n, self.feedback, self.diff, self.ci_out = 0, None, "", ""

    @property
    def cid(self):
        return self.card.id


class Plan:
    """The planner never changes code; a vague card stops here with questions."""

    def run(self, p, j):
        p.log.state(card=j.cid, phase="plan")
        t = time.time()
        out = p._ask("planner", j.agent, f"PHASE=PLAN. Card: {j.card.path.as_posix()}. Follow your agent instructions and CLAUDE.md.")
        p.log.artifact(j.cid, "plan.txt", out)
        m = marker(out)
        if m == "BLOCKED":
            p.log.event("plan", j.cid, j.agent, "blocked: questions in card", time.time() - t)
            return block("vague or missing info, see Blockers / questions")
        if m != "PLANNED" or not re.search(r"^- \[ \]", j.card.section("Tasks"), re.MULTILINE):
            p.log.event("plan", j.cid, j.agent, "invalid plan", time.time() - t)
            return block("planner did not produce a RESULT marker and a ## Tasks checklist")
        p.log.event("plan", j.cid, j.agent, "planned", time.time() - t)
        return PASS


class Build:
    def run(self, p, j):
        g, n = p.cfg, j.n
        p.log.state(card=j.cid, phase=f"build {n}/{g['max_attempts']}")
        t = time.time()
        out = p._team(j.card, j.agent, n, j.feedback) if n == 1 else None
        if out is None:
            out = p._ask("builder", j.agent, f"PHASE=IMPLEMENT, attempt {n} of {g['max_attempts']}. "
                                             f"Card: {j.card.path.as_posix()}. Feedback from the previous attempt (empty on the first): {j.feedback.as_posix()}")
        p.log.artifact(j.cid, f"build{n}.txt", out)
        if marker(out) == "BLOCKED":
            p.log.event("build", j.cid, j.agent, f"attempt {n}: blocked", time.time() - t)
            return block("builder found missing info, see Blockers / questions")
        p.log.event("build", j.cid, j.agent, f"attempt {n}: done", time.time() - t)
        return PASS


class Guardrails:
    """Rules in code, not in prompts: protected paths, size, secrets, deleted tests."""

    def run(self, p, j):
        p.log.state(card=j.cid, phase=f"guardrails {j.n}")
        p.git.add_all()
        j.diff = p.git.diff_cached(p.base)
        viol = guardrails.check_diff(p.cfg["guardrails"], p.git.changed(p.base), p.git.changed(p.base, deleted=True), j.diff)
        if not viol:
            return PASS
        p.log.event("guardrails", j.cid, "guardrails", f"attempt {j.n}: {len(viol)} violation(s)")
        for v in viol:
            p.log.say("pipeline", f"   ! {v}")
        j.card.log(f"attempt {j.n}: guardrails: " + "; ".join(viol))
        return retry("GUARDRAIL VIOLATIONS. Fix these:\n- " + "\n- ".join(viol))


class CI:
    def run(self, p, j):
        p.log.state(card=j.cid, phase=f"ci {j.n}")
        t = time.time()
        ci, j.ci_out = p._ci()
        p.log.artifact(j.cid, f"ci{j.n}.txt", j.ci_out)
        p.log.say("pipeline", "\n".join("   | " + ln for ln in j.ci_out.splitlines()[-2:]))
        if ci.returncode:
            p.log.event("ci", j.cid, "ci", f"attempt {j.n}: FAIL", time.time() - t)
            j.card.log(f"attempt {j.n}: CI failed")
            return retry("CI FAILED. Fix these:\n" + "\n".join(j.ci_out.splitlines()[-80:]))
        p.log.event("ci", j.cid, "ci", "PASS", time.time() - t)
        return PASS


class Review:
    """Independent reviewers, in parallel. All must approve."""

    def run(self, p, j):
        p.log.state(card=j.cid, phase=f"review {j.n}")
        review = p.log.artifact(j.cid, f"review{j.n}.txt", "# CARD\n" + j.card.for_review() + "\n\n# DIFF\n" + j.diff +
                                "\n\n# CI OUTPUT (tail)\n" + "\n".join(j.ci_out.splitlines()[-60:]))
        results = p._review(j.cid, review)
        for name, (v, _) in results.items():
            p.log.event("review", j.cid, name, v)
        if all(v == "APPROVED" for v, _ in results.values()):
            return APPROVED
        j.card.log(f"attempt {j.n} rejected ({', '.join(f'{k}={v}' for k, (v, _) in results.items())})")
        return retry("REVIEW REJECTED. Fix these failures.\n" + "\n".join(f"## {k}\n{o}" for k, (_, o) in results.items()))
