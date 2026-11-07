"""End-to-end pipeline with a fake agent runner and a real temp git repo."""
import sys

from conftest import add_card

from orch.pipeline import Pipeline

TASKS = "## Tasks\n- [ ] make thing (criterion 1, test_thing)\n"


class Fake:
    """claude(role, agent, prompt) / agy(role, model, prompt) with scripted behavior."""

    def __init__(self, project, plan="RESULT: PLANNED", build=None, qa="VERDICT: APPROVED", gem="VERDICT: APPROVED", split=None):
        self.p, self.plan, self.build, self.qa, self.gem, self.calls, self.models, self.split = project, plan, build, qa, gem, [], {}, split

    def claude(self, role, agent, prompt, model=None):
        self.calls.append(role)
        self.models[role] = model
        card = next(self.p.glob("board/doing/*.md"), None)
        if role == "splitter":
            return self.split(self.p) if self.split else "RESULT: SINGLE"
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

    def provider(self, role, provider, model, prompt, mode="read"):
        return self.agy(role, model, prompt)


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
    cfg["ci"] = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
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


def test_splitter_breaks_big_card_into_children_that_run_in_the_same_run(project, cfg, log):
    from conftest import CARD

    def split(p):
        for n in (1, 2):
            (p / "board" / "backlog" / f"001-thing-{n}-part.md").write_text(CARD.replace("Add thing", f"Part {n}"), encoding="utf-8")
        return "RESULT: SPLIT"

    def build(p):
        doing = next(p.glob("board/doing/*.md")).stem
        (p / f"{doing}.py").write_text("x = 1\n")

    add_card(project)
    calls = Fake(project, split=lambda p: split(p) if not list(p.glob("board/*/001-thing-*.md")) else "RESULT: SINGLE", build=build)
    run(project, cfg, log, calls)
    assert sorted(names(project, "done")) == ["001-thing-1-part.md", "001-thing-2-part.md", "001-thing.md"]
    assert calls.calls.count("builder") == 2                      # parent itself was never built
    assert (project / "001-thing-1-part.py").exists() and (project / "001-thing-2-part.py").exists()


def test_splitter_invalid_children_fall_back_to_whole_card(project, cfg, log):
    def bad_split(p):
        (p / "board" / "backlog" / "001-thing-1-x.md").write_text("---\ntitle: x\n---\n# x\n", encoding="utf-8")
        return "RESULT: SPLIT"

    add_card(project)
    fake = Fake(project, split=bad_split)
    run(project, cfg, log, fake)
    assert names(project, "done") == ["001-thing.md"] and fake.calls.count("builder") == 1


def test_splitter_can_block_vague_card(project, cfg, log):
    add_card(project)
    fake = Fake(project, split=lambda p: "RESULT: BLOCKED")
    run(project, cfg, log, fake)
    assert names(project, "blocked") == ["001-thing.md"] and "planner" not in fake.calls
