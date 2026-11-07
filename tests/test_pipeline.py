"""End-to-end pipeline with a fake agent runner and a real temp git repo."""
from conftest import add_card

from orch.pipeline import Pipeline

TASKS = "## Tasks\n- [ ] make thing (criterion 1, test_thing)\n"


class Fake:
    """claude(role, agent, prompt) / agy(role, model, prompt) with scripted behavior."""

    def __init__(self, project, plan="RESULT: PLANNED", build=None, qa="VERDICT: APPROVED", gem="VERDICT: APPROVED"):
        self.p, self.plan, self.build, self.qa, self.gem, self.calls, self.models = project, plan, build, qa, gem, [], {}

    def claude(self, role, agent, prompt, model=None):
        self.calls.append(role)
        self.models[role] = model
        card = next(self.p.glob("board/doing/*.md"), None)
        if role == "planner":
            if card and "BLOCKED" not in self.plan:
                card.write_text(card.read_text(encoding="utf-8").replace("## Tasks\n", TASKS), encoding="utf-8")
            return self.plan
        if role == "builder":
            (self.build or (lambda p: (p / "thing.py").write_text("def thing():\n    return 1\n")))(self.p)
            return "RESULT: DONE"
        if role == "qa":
            return self.qa
        return "ok"

    def agy(self, role, model, prompt):
        self.calls.append(role)
        return self.gem


def run(project, cfg, log, fake, **kw):
    p = Pipeline(project, cfg, log, fake)
    assert p.run(**kw) == 0
    return p


def names(project, state):
    return [c.name for c in (project / "board" / state).glob("*.md")]


def test_happy_path_merges_and_retro(project, cfg, log):
    add_card(project)
    fake = Fake(project)
    run(project, cfg, log, fake)
    assert names(project, "done") == ["001-thing.md"]
    assert (project / "thing.py").exists()                       # merged into main
    assert fake.calls.count("builder") == 1 and "retro" in fake.calls
    assert fake.models["builder"] == "sonnet"                    # role models come from config
    assert "001-thing" in (project / "context" / "history.md").read_text(encoding="utf-8")
    assert (log.dir / "events.jsonl").read_text(encoding="utf-8").count("card_done") == 1


def test_vague_card_blocks_without_building(project, cfg, log):
    add_card(project)
    fake = Fake(project, plan="questions\nRESULT: BLOCKED")
    run(project, cfg, log, fake)
    assert names(project, "blocked") == ["001-thing.md"] and "builder" not in fake.calls
    assert not (project / "thing.py").exists()


def test_invalid_card_blocks_before_any_agent(project, cfg, log):
    add_card(project, text="---\ntitle: x\narea: backend\n---\n# x\n")
    fake = Fake(project)
    run(project, cfg, log, fake)
    assert names(project, "blocked") == ["001-thing.md"] and fake.calls == ["retro"]


def test_rejection_retries_then_blocks_after_max_attempts(project, cfg, log):
    add_card(project)
    fake = Fake(project, gem="VERDICT: REJECTED\nmissing edge case")
    run(project, cfg, log, fake)
    assert names(project, "blocked") == ["001-thing.md"]
    assert fake.calls.count("builder") == 3                       # 3-attempt limit
    assert not (project / "thing.py").exists()                    # nothing merged to main
    assert project.joinpath(".git").exists() and "card/001-thing" in __import__("subprocess").run(
        ["git", "branch"], cwd=project, capture_output=True, text=True).stdout   # WIP kept for the human


def test_guardrail_violation_never_reaches_review(project, cfg, log):
    add_card(project)

    def bad(p):
        (p / "scripts").mkdir(exist_ok=True)
        (p / "scripts" / "ci.sh").write_text("exit 0\n")

    fake = Fake(project, build=bad)
    run(project, cfg, log, fake)
    assert names(project, "blocked") == ["001-thing.md"]
    assert "qa" not in fake.calls and "cross" not in fake.calls   # stopped by guardrails every time


def test_ci_failure_goes_back_to_builder(project, cfg, log):
    add_card(project)
    cfg["ci"] = 'python -c "import sys; sys.exit(1)"'
    fake = Fake(project)
    run(project, cfg, log, fake)
    assert names(project, "blocked") == ["001-thing.md"] and "qa" not in fake.calls
    assert fake.calls.count("builder") == 3


def test_second_attempt_can_succeed(project, cfg, log):
    add_card(project)
    verdicts = iter(["VERDICT: REJECTED", "VERDICT: APPROVED"])
    fake = Fake(project)
    fake.agy = lambda role, model, prompt: (fake.calls.append(role), next(verdicts))[1]
    run(project, cfg, log, fake)
    assert names(project, "done") == ["001-thing.md"] and fake.calls.count("builder") == 2
