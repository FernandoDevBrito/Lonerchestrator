from pathlib import Path

from conftest import CARD, add_card
from test_pipeline import Fake, names

from orch import answer, tui
from orch.board import Card
from orch.cli import main
from orch.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent.parent
WITH_OPTIONS = ("1. Which output format should the report use?\n"
                "   a) Plain text summary on stdout\n"
                "   b) CSV file in out/report.csv\n"
                "   c) Markdown file\n"
                "      in out/report.md\n"
                "2. Where to write it?\n"
                "   A) out/\n"
                "   - b) the current folder\n"
                "   c) a path I will give\n")


def blocked(project, questions=WITH_OPTIONS, name="001-thing"):
    f = project / "board" / "blocked" / f"{name}.md"
    f.write_text(CARD.replace("## Blockers / questions\n", "## Blockers / questions\n" + questions), encoding="utf-8")
    return Card(f)


# ---- reading the questions ---------------------------------------------------------------------------------------
def test_parse_reads_three_options_per_question_including_wrapped_and_bulleted(project):
    qs = answer.parse(blocked(project))
    assert [q.text for q in qs] == ["Which output format should the report use?", "Where to write it?"]
    assert qs[0].options == ["Plain text summary on stdout", "CSV file in out/report.csv", "Markdown file in out/report.md"]
    assert qs[1].options == ["out/", "the current folder", "a path I will give"]
    assert answer.questions(blocked(project, name="002-x")) == [q.text for q in qs]               # the old API still works
    assert answer.missing_options(blocked(project, name="003-y")) is False


def test_missing_options_flags_questions_that_ignore_the_format(project):
    assert answer.missing_options(blocked(project, "1. Which format?\n2. Where?\n", "001-a")) is True              # old style, no suggestions
    assert answer.missing_options(blocked(project, "1. Which format?\n   a) csv\n   b) json\n", "002-b")) is True   # only two
    assert answer.missing_options(blocked(project, "It is not clear what fast means.\n", "003-c")) is True          # free text
    none = Card(project / "board" / "blocked" / "004-d.md")
    none.path.write_text(CARD, encoding="utf-8")
    assert answer.parse(none) == [] and answer.missing_options(none) is False


def test_pick_maps_digits_to_suggestions_and_keeps_everything_else(project):
    q = answer.parse(blocked(project))[0]
    assert answer.pick(q, "2") == "CSV file in out/report.csv" and answer.pick(q, " 1 ") == "Plain text summary on stdout"
    assert answer.pick(q, "4") == "4" and answer.pick(q, "0") == "0"                              # not a suggestion: the user's own text
    assert answer.pick(q, "csv please") == "csv please" and answer.pick(q, "") == ""


def test_apply_accepts_question_objects_and_stores_the_chosen_text(project):
    c = blocked(project)
    qs = answer.parse(c)
    assert answer.apply(c, qs, [answer.pick(qs[0], "3"), "somewhere else"])
    assert "-> Markdown file in out/report.md" in c.section("Answers") and "-> somewhere else" in c.section("Answers")


# ---- the panel -----------------------------------------------------------------------------------------------------
def open_answer(project):
    ui = tui.UI()
    ui.screen, ui.col = 2, 3
    return ui


def press(project, ui, *keys):
    for k in keys:
        tui.handle(k, ui, tui.Ctx(project, ui), None)


def test_number_keys_pick_a_suggestion_and_move_to_the_next_question(project):
    blocked(project)
    ui = open_answer(project)
    press(project, ui, "a")
    out = tui.render(project, 2, ui=ui, color=False)
    assert "1  Plain text summary on stdout" in out and "3  Markdown file" in out and "press 1-3 to pick a suggestion" in out
    assert "1-3 pick a suggestion" in out and {tui.vlen(ln) for ln in out.split("\n")} == {tui.W}
    press(project, ui, "2")
    assert ui.ans == ["CSV file in out/report.csv"] and ui.mode == "answer" and ui.buf == ""
    press(project, ui, "1")                                                  # last question: picking it finishes everything
    assert ui.mode is None and "queued" in ui.msg
    c = Card(project / "board" / "backlog" / "001-thing.md")
    assert "-> CSV file in out/report.csv" in c.section("Answers") and "-> out/" in c.section("Answers")


def test_typing_your_own_answer_still_works_and_digits_are_text_once_typing_started(project):
    blocked(project)
    ui = open_answer(project)
    press(project, ui, "a")
    press(project, ui, *"HTML", "2", "\r")                                   # "2" after other characters is plain text
    assert ui.ans == ["HTML2"]
    press(project, ui, "7", *" files", "\r")                                 # a digit with no such suggestion is text too
    assert ui.mode is None
    assert "-> HTML2" in Card(project / "board" / "backlog" / "001-thing.md").section("Answers") and "-> 7 files" in Card(
        project / "board" / "backlog" / "001-thing.md").section("Answers")


def test_questions_without_suggestions_keep_the_old_behaviour(project):
    blocked(project, "1. Which format?\n2. Where?\n")
    ui = open_answer(project)
    press(project, ui, "a")
    out = tui.render(project, 2, ui=ui, color=False)
    assert "press 1-" not in out and "Your answer" in out
    press(project, ui, "1")                                                   # no suggestions: the digit is just text
    assert ui.buf == "1" and ui.ans == []


def test_backspace_after_a_pick_does_not_reappear_and_escape_cancels(project):
    blocked(project)
    ui = open_answer(project)
    press(project, ui, "a", "x", "\x7f", "3")                                # typed then erased: buffer empty again, so 3 picks
    assert ui.ans == ["Markdown file in out/report.md"]
    press(project, ui, "\x1b")
    assert ui.mode is None and (project / "board" / "blocked" / "001-thing.md").exists()


# ---- the terminal command ------------------------------------------------------------------------------------------
def test_cli_answer_shows_suggestions_and_accepts_numbers_or_text(project, monkeypatch, capsys):
    blocked(project)
    given = iter(["2", "my own folder"])
    monkeypatch.setattr("builtins.input", lambda *_: next(given))
    assert main(["-C", str(project), "answer", "001"]) == 0
    out = capsys.readouterr().out
    assert "1) Plain text summary on stdout" in out and "2) CSV file in out/report.csv" in out and "Type 1-3" in out
    c = Card(project / "board" / "backlog" / "001-thing.md")
    assert "-> CSV file in out/report.csv" in c.section("Answers") and "-> my own folder" in c.section("Answers")


# ---- agents are told to write the suggestions -------------------------------------------------------------------------------
def test_agent_instructions_ask_for_three_suggested_answers():
    base = ROOT / "orch" / "templates"
    for agent in ("backend", "frontend", "splitter"):
        text = (base / "dot-claude" / "agents" / f"{agent}.md").read_text(encoding="utf-8")
        assert "exactly THREE suggested answers" in text and "a) <concrete suggested answer>" in text, agent
    assert "three suggested answers" in (base / "dot-claude" / "skills" / "card-workflow" / "SKILL.md").read_text(encoding="utf-8")
    assert "3 suggested answers" in (base / "board" / "_TEMPLATE.md").read_text(encoding="utf-8")


class AsksWith(Fake):
    """Planner that blocks the card with the given questions."""

    def __init__(self, project, questions):
        super().__init__(project)
        self.questions = questions

    def claude(self, role, agent, prompt, model=None):
        if role != "planner":
            return super().claude(role, agent, prompt, model)
        self.calls.append(role)
        Card(next(self.p.glob("board/doing/*.md"))).set_section("Blockers", self.questions)
        return "RESULT: BLOCKED"


def test_the_card_log_notes_when_an_agent_ignored_the_suggestions_format(project, cfg, log):
    add_card(project)
    assert Pipeline(project, cfg, log, AsksWith(project, "1. Which format?\n2. Where?")).run() == 0
    assert names(project, "blocked") == ["001-thing.md"]
    assert "no 3 suggested answers" in Card(project / "board" / "blocked" / "001-thing.md").section("Status log")


def test_no_note_when_the_agent_followed_the_format(project, cfg, log):
    add_card(project)
    Pipeline(project, cfg, log, AsksWith(project, WITH_OPTIONS)).run()
    assert "no 3 suggested answers" not in Card(project / "board" / "blocked" / "001-thing.md").section("Status log")
    assert [q.options for q in answer.parse(Card(project / "board" / "blocked" / "001-thing.md"))][0][0] == "Plain text summary on stdout"
