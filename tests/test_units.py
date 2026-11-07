from conftest import CARD

from orch import agents, config, guardrails
from orch.board import Card

G = config.DEFAULTS["guardrails"]


def card(tmp_path, text=CARD):
    f = tmp_path / "board" / "backlog" / "001-x.md"
    f.parent.mkdir(parents=True)
    f.write_text(text, encoding="utf-8")
    return Card(f)


def test_card_parse_and_set(tmp_path):
    c = card(tmp_path)
    assert (c.title, c.area, c.get("attempts")) == ("Add thing", "backend", "0")
    c.set("attempts", 2)
    assert c.get("attempts") == "2"
    assert c.section("Goal") == "Add a thing."
    assert c.problems() == []


def test_card_problems(tmp_path):
    c = card(tmp_path, CARD.replace("area: backend", "area: mobile").replace("- [ ] thing() returns 1", ""))
    assert len(c.problems()) == 2


def test_for_review_hides_plan_tasks_log(tmp_path):
    c = card(tmp_path, CARD.replace("## Plan\n", "## Plan\nsecret reasoning\n"))
    r = c.for_review()
    assert "secret reasoning" not in r and "Acceptance criteria" in r and "Status log" not in r


def test_card_move_and_log(tmp_path):
    c = card(tmp_path)
    c.move("doing")
    assert c.path.parent.name == "doing"
    c.log("hello")
    assert "hello" in c.section("Status log")


def test_verdict_and_marker():
    assert agents.verdict("blah\nVERDICT: APPROVED") == "APPROVED"
    assert agents.verdict("no verdict") == "REJECTED"
    assert agents.verdict("VERDICT: APPROVED\nVERDICT: REJECTED") == "REJECTED"
    assert agents.marker("x\nRESULT: PLANNED") == "PLANNED" and agents.marker("x") == ""


def test_guardrails():
    assert guardrails.check_diff(G, ["src/a.py"], [], "+x = 1\n") == []
    assert any("protected" in v for v in guardrails.check_diff(G, ["scripts/ci.sh"], [], ""))
    assert any("test file deleted" in v for v in guardrails.check_diff(G, [], ["tests/test_a.py"], ""))
    assert any("secret" in v for v in guardrails.check_diff(G, ["a.py"], [], '+api_key = "abcdefghijklmnop"\n'))
    assert any("files changed" in v for v in guardrails.check_diff({**G, "max_files": 1}, ["a", "b"], [], ""))
    assert any("changed lines" in v for v in guardrails.check_diff({**G, "max_diff_lines": 1}, ["a"], [], "+a\n+b\n"))


def test_rate_limit_backoff(project, cfg, log):
    waits, calls = [], []
    r = agents.Runner(project, cfg, log, sleep=waits.append)
    seq = iter([(1, "", "429 rate limit"), (1, "", "usage limit reached"), (0, "ok", "ok")])
    r._once = lambda *a: calls.append(1) or next(seq)
    assert r._run("builder", ["x"], False) == "ok"
    assert waits == [60, 120] and len(calls) == 3


def test_auth_and_exhausted(project, cfg, log):
    import pytest
    r = agents.Runner(project, cfg, log, sleep=lambda s: None)
    r._once = lambda *a: (1, "", "Failed to authenticate: OAuth session expired")
    with pytest.raises(agents.AuthError):
        r._run("qa", ["x"], True)
    cfg["rate_limit"]["max_waits"] = 2
    r._once = lambda *a: (1, "", "rate limit")
    with pytest.raises(agents.RateLimitExhausted):
        r._run("qa", ["x"], True)
