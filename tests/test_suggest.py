import json
import subprocess
from types import SimpleNamespace

from conftest import CARD, home

from orch import answer, suggest, tui, usage
from orch.board import Card
from orch.cli import main
from orch.suggest import ask_claude as real_ask_claude  # the autouse fixture replaces suggest.ask_claude: keep the real one
from orch.suggest import parse_reply

TWO_PLAIN = "1. Which format?\n2. Where to write it?\n"
FULL_AND_PLAIN = "1. Which format?\n   a) csv\n   b) json\n   c) text\n2. Where to write it?\n"
REPLY = json.dumps([["CSV", "JSON", "Plain text"], ["out/", "the current folder", "a path I will give"]])


def blocked(project, questions=TWO_PLAIN, name="001-thing", goal="Add a nightly report"):
    f = home(project) / "board" / "blocked" / f"{name}.md"
    f.write_text(CARD.replace("Add a thing.", goal).replace("## Blockers / questions\n", "## Blockers / questions\n" + questions), encoding="utf-8")
    return Card(f)


# ---- reading Claude's reply ---------------------------------------------------------------------------------------------
def test_parse_reply_accepts_json_even_with_prose_or_fences_around_it():
    assert parse_reply(REPLY, 2) == [["CSV", "JSON", "Plain text"], ["out/", "the current folder", "a path I will give"]]
    assert parse_reply("Sure! Here you go:\n```json\n" + REPLY + "\n```\nHope it helps.", 2)[0][0] == "CSV"
    assert parse_reply('[["a  b", " c ", "d", "e"]]', 1) == [["a b", "c", "d"]]                  # whitespace collapsed, capped at three


def test_parse_reply_rejects_anything_unusable():
    for bad in (None, "", "no json here", "[1, 2]", '[["a"]]', "[[]]", '{"a": 1}', "[[\"a\"], [\"b\"]"):
        assert parse_reply(bad, 2) is None, bad
    assert parse_reply('[["a", "b", "c"]]', 2) is None                                              # one answer set for two questions


# ---- the Claude call itself ----------------------------------------------------------------------------------------------
def fake_run(stdout, rc=0, seen=None):
    def run(argv, **kw):
        if seen is not None:
            seen.append(argv)
        return SimpleNamespace(stdout=stdout, returncode=rc)
    return run


def stream(text, limit=None, error=False):
    evs = []
    if limit:
        evs.append({"type": "rate_limit_event", "rate_limit_info": limit})
    evs.append({"type": "result", "result": text, "is_error": error})
    return "\n".join(json.dumps(e) for e in evs)


def test_ask_claude_is_read_only_cheap_and_returns_the_reply(monkeypatch):
    seen = []
    monkeypatch.setattr(suggest.shutil, "which", lambda n: "/bin/claude")
    monkeypatch.setattr(suggest.subprocess, "run", fake_run(stream("hello"), seen=seen))
    assert real_ask_claude("my prompt") == "hello"
    argv = seen[0]
    assert argv[-1] == "my prompt" and argv[argv.index("--model") + 1] == "haiku"
    assert "--agent" not in argv and "acceptEdits" not in " ".join(argv)                           # no agent, no edit permission: it cannot touch files


def test_ask_claude_feeds_the_account_limits(monkeypatch):
    lim = {"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.4, "resetsAt": 9, "status": "allowed"}}}
    monkeypatch.setattr(suggest.shutil, "which", lambda n: "/bin/claude")
    monkeypatch.setattr(suggest.subprocess, "run", fake_run(stream("x", limit=lim)))
    real_ask_claude("p")
    assert usage.read_limits()["claude"]["windows"]["five_hour"]["utilization"] == 0.4


def test_ask_claude_returns_none_when_it_cannot_help(monkeypatch):
    monkeypatch.setattr(suggest.shutil, "which", lambda n: None)
    assert real_ask_claude("p") is None                                                            # not installed
    monkeypatch.setattr(suggest.shutil, "which", lambda n: "/bin/claude")
    monkeypatch.setattr(suggest.subprocess, "run", fake_run(stream("x"), rc=1))
    assert real_ask_claude("p") is None                                                            # failed / not logged in
    monkeypatch.setattr(suggest.subprocess, "run", fake_run(stream("x", error=True)))
    assert real_ask_claude("p") is None                                                            # an error result is not an answer

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("claude", 1)

    monkeypatch.setattr(suggest.subprocess, "run", boom)
    assert real_ask_claude("p") is None


# ---- filling the card -----------------------------------------------------------------------------------------------------
def test_add_suggestions_writes_three_options_for_every_question(project):
    c = blocked(project)
    prompts = []
    assert answer.add_suggestions(c, ask=lambda p: prompts.append(p) or REPLY) is True
    qs = answer.parse(c)
    assert [q.options for q in qs] == [["CSV", "JSON", "Plain text"], ["out/", "the current folder", "a path I will give"]]
    assert [q.text for q in qs] == ["Which format?", "Where to write it?"] and answer.missing_options(c) is False
    assert len(prompts) == 1 and "Add a nightly report" in prompts[0] and "THREE" in prompts[0] and "JSON array of 2 arrays" in prompts[0]


def test_only_the_questions_without_suggestions_are_asked_and_existing_ones_are_kept(project):
    c = blocked(project, FULL_AND_PLAIN)
    seen = []
    assert answer.add_suggestions(c, ask=lambda p: seen.append(p) or '[["out/", "here", "elsewhere"]]')
    qs = answer.parse(c)
    assert qs[0].options == ["csv", "json", "text"] and qs[1].options == ["out/", "here", "elsewhere"]
    assert "Where to write it?" in seen[0] and "Which format?" not in seen[0] and "1. Where to write it?" in seen[0]


def test_the_prompt_carries_what_the_user_already_answered(project):
    c = blocked(project)
    c.set_section("Answers", "1. Which engine?\n   -> SQLite")
    seen = []
    answer.add_suggestions(c, ask=lambda p: seen.append(p) or REPLY)
    assert "already answered" in seen[0] and "-> SQLite" in seen[0]


def test_a_bad_or_missing_reply_leaves_the_card_exactly_as_it_was(project):
    c = blocked(project)
    before = c.text()
    assert answer.add_suggestions(c, ask=lambda p: "sorry, I cannot") is False
    assert answer.add_suggestions(c, ask=lambda p: None) is False
    assert answer.add_suggestions(c, ask=lambda p: '[["only one set"]]') is False
    assert c.text() == before


def test_nothing_is_asked_when_every_question_already_has_suggestions(project):
    c = blocked(project, "1. Which format?\n   a) csv\n   b) json\n   c) text\n")
    assert answer.add_suggestions(c, ask=lambda p: 1 / 0) is False


def test_render_and_parse_round_trip(project):
    qs = [answer.Question("A?", ["x", "y", "z"]), answer.Question("B?", [])]
    c = blocked(project, answer.render(qs))
    assert [(q.text, q.options) for q in answer.parse(c)] == [("A?", ["x", "y", "z"]), ("B?", [])]


# ---- the panel -------------------------------------------------------------------------------------------------------------
def start(project):
    ui = tui.UI()
    ui.screen, ui.col = 2, 3
    tui.handle("a", ui, tui.Ctx(project, ui), None)
    return ui


def test_pressing_a_fetches_suggestions_for_a_card_that_has_none(project, monkeypatch):
    blocked(project)
    monkeypatch.setattr(suggest, "ask_claude", lambda *a, **k: REPLY)
    ui = start(project)
    assert ui.suggesting is False and ui.qopts[0] == ["CSV", "JSON", "Plain text"]
    out = tui.render(project, 2, ui=ui, color=False)
    assert "1  CSV" in out and "3  Plain text" in out and "press 1-3" in out
    tui.handle("2", ui, tui.Ctx(project, ui), None)
    assert ui.ans == ["JSON"]
    assert "Which format?\n   a) CSV" in (home(project) / "board" / "blocked" / "001-thing.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_while_waiting_the_panel_says_so_and_typing_already_works(project, monkeypatch):
    blocked(project)
    monkeypatch.setattr(tui, "_bg", lambda fn: None)                          # the job has not finished yet
    ui = start(project)
    assert ui.suggesting is True
    out = tui.render(project, 2, ui=ui, color=False)
    assert "asking Claude for 3 suggested answers" in out and {tui.vlen(ln) for ln in out.split("\n")} == {tui.W}
    for k in "csv":
        tui.handle(k, ui, tui.Ctx(project, ui), None)
    tui.handle("\r", ui, tui.Ctx(project, ui), None)
    assert ui.ans == ["csv"]


def test_if_claude_cannot_help_the_user_just_types(project):
    blocked(project)                                                           # the autouse fake returns None
    ui = start(project)
    assert ui.suggesting is False and ui.qopts == [[], []]
    tui.handle("1", ui, tui.Ctx(project, ui), None)
    assert ui.buf == "1"                                                       # no suggestions: the digit is text


def test_a_late_reply_after_the_card_was_answered_is_harmless(project, monkeypatch):
    c = blocked(project)
    ui = start(project)
    answer.apply(c, answer.parse(c), ["x", "y"])                               # answered and moved to the backlog meanwhile
    ui.mode = None
    monkeypatch.setattr(suggest, "ask_claude", lambda *a, **k: REPLY)
    tui._fill_suggestions(ui, c)                                               # must not raise
    assert ui.suggesting is False


# ---- the terminal command ----------------------------------------------------------------------------------------------------
def test_cli_answer_fetches_suggestions_first(project, monkeypatch, capsys):
    blocked(project)
    monkeypatch.setattr(suggest, "ask_claude", lambda *a, **k: REPLY)
    given = iter(["2", "my own"])
    monkeypatch.setattr("builtins.input", lambda *_: next(given))
    assert main(["-C", str(project), "answer", "001"]) == 0
    out = capsys.readouterr().out
    assert "asking Claude for 3 per question" in out and "1) CSV" in out and "3) Plain text" in out
    c = Card(home(project) / "board" / "backlog" / "001-thing.md")
    assert "-> JSON" in c.section("Answers") and "-> my own" in c.section("Answers")


def test_cli_answer_still_works_when_suggestions_are_unavailable(project, monkeypatch, capsys):
    blocked(project)
    given = iter(["csv", "here"])
    monkeypatch.setattr("builtins.input", lambda *_: next(given))
    assert main(["-C", str(project), "answer", "001"]) == 0
    assert "could not get suggestions" in capsys.readouterr().out
    assert "-> csv" in Card(home(project) / "board" / "backlog" / "001-thing.md").section("Answers")
