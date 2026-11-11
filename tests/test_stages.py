"""The pipeline is a list of stages: a new step is a class with run(p, job), and workspaces share one small interface."""
from conftest import add_card, home
from test_pipeline import Fake, names

from orch import stages
from orch.parallel import Hub
from orch.pipeline import InPlace, Pipeline


class Veto:
    """A made-up extra stage, e.g. a security scan: blocks the card before the reviewers see it."""

    def run(self, p, j):
        return stages.block("scan found a secret")


class FixOnce:
    """Fails the first attempt with feedback, passes after."""

    def run(self, p, j):
        return stages.retry("FIX IT: the scan wants a docstring") if j.n == 1 else stages.PASS


def test_a_new_stage_can_block_a_card_before_review(project, cfg, log):
    add_card(project)
    fake = Fake(project)
    p = Pipeline(project, cfg, log, fake)
    p.stages.insert(3, Veto())                                       # after Build, Guardrails, CI; before Review
    assert p.run() == 0
    assert names(project, "blocked") == ["001-thing.md"] and not names(project, "done")
    assert "qa" not in fake.calls and "scan found a secret" in (home(project) / "board" / "blocked" / "001-thing.md").read_text(encoding="utf-8")


def test_a_stage_that_retries_gives_the_builder_its_feedback_and_another_attempt(project, cfg, log):
    add_card(project)
    fake = Fake(project)
    p = Pipeline(project, cfg, log, fake)
    p.stages.insert(1, FixOnce())
    assert p.run() == 0
    assert fake.calls.count("builder") == 2 and names(project, "done") == ["001-thing.md"]
    fb = next((home(project) / "runs").glob("*/001-thing/feedback.txt")).read_text(encoding="utf-8")
    assert fb == "FIX IT: the scan wants a docstring"


def test_the_stages_run_in_order_and_the_default_list_is_the_documented_one(project, cfg, log):
    p = Pipeline(project, cfg, log, Fake(project))
    assert [type(s).__name__ for s in p.stages] == ["Build", "Guardrails", "CI", "Review"] and type(p.plan).__name__ == "Plan"
    assert stages.PASS.kind == "pass" and stages.retry("x").kind == "retry" and stages.block("y").text == "y" and stages.APPROVED.kind == "approved"


def test_both_workspaces_offer_the_same_methods_and_the_default_is_in_place(project, cfg, log):
    assert isinstance(Pipeline(project, cfg, log, Fake(project)).ws, InPlace)
    main = Pipeline(project, cfg, log, Fake(project))
    hub = Hub(main)
    assert isinstance(Pipeline(project, cfg, log, Fake(project), hub=hub).ws, Hub)
    for ws in (InPlace(), hub):
        assert all(callable(getattr(ws, m)) for m in ("merge", "park", "retro")) and hasattr(ws, "lock")
