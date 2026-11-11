from conftest import CARD, home
from test_pipeline import TASKS, Fake, names

from orch import answer, tui
from orch.board import Card
from orch.cli import main
from orch.pipeline import Pipeline

ASKED = CARD.replace("## Blockers / questions\n", "## Blockers / questions\n1. Which format?\n   (csv or json)\n2. Where to write it?\n")


def blocked_card(project, name="001-thing", text=ASKED):
    f = home(project) / "board" / "blocked" / f"{name}.md"
    f.write_text(text, encoding="utf-8")
    return Card(f)


def test_questions_numbered_wrapped_and_free_text(project):
    assert answer.questions(blocked_card(project)) == ["Which format? (csv or json)", "Where to write it?"]
    free = blocked_card(project, "002-free", CARD.replace("## Blockers / questions\n", "## Blockers / questions\nIt is not clear what 'fast' means.\n"))
    assert answer.questions(free) == ["It is not clear what 'fast' means."]
    assert answer.questions(blocked_card(project, "003-none", CARD)) == []


def test_set_section_replaces_inserts_and_clears(project):
    c = blocked_card(project)
    c.set_section("Goal", "New goal.")
    assert c.section("Goal") == "New goal." and c.section("Acceptance criteria").startswith("- [ ] thing()")
    c.set_section("Answers", "1. x")                      # missing -> inserted before the status log
    t = c.text()
    assert t.index("## Answers") < t.index("## Status log") and c.section("Answers") == "1. x"
    c.set_section("Blockers", "")
    assert c.section("Blockers") == "" and "## Blockers / questions" in c.text()


def test_apply_stores_answers_requeues_and_keeps_earlier_rounds(project):
    c = blocked_card(project)
    c.set("attempts", 3)
    qs = answer.questions(c)
    assert answer.apply(c, qs, ["CSV", ""]) is True
    assert c.path.parent.name == "backlog" and c.get("attempts") == "0" and c.section("Blockers") == ""
    assert "-> CSV" in c.section("Answers") and "(no answer)" in c.section("Answers")
    assert "answered by the user" in c.section("Status log")
    c.set_section("Blockers", "1. And the delimiter?")
    c.move("blocked")
    answer.apply(c, ["And the delimiter?"], [";"])
    assert "-> CSV" in c.section("Answers") and "-> ;" in c.section("Answers")           # round 1 is still there


def test_all_empty_answers_change_nothing(project):
    c = blocked_card(project)
    before = c.text()
    assert answer.apply(c, answer.questions(c), ["", "  "]) is False
    assert c.path.parent.name == "blocked" and c.text() == before


class AskingFake(Fake):
    """Planner asks questions until the card has answers, then plans."""

    seen = ""

    def claude(self, role, agent, prompt, model=None):
        if role != "planner":
            return super().claude(role, agent, prompt, model)
        self.calls.append(role)
        card = Card(next(home(self.p).glob("board/doing/*.md")))
        if "-> CSV" in card.section("Answers"):
            self.seen = card.section("Answers")
            card.path.write_text(card.text().replace("## Tasks\n", TASKS), encoding="utf-8")
            return "RESULT: PLANNED"
        card.set_section("Blockers", "1. Which format?\n2. Where to write it?")
        return "RESULT: BLOCKED"


def test_full_cycle_ask_answer_run_again(project, cfg, log):
    from conftest import add_card
    add_card(project)
    fake = AskingFake(project)
    assert Pipeline(project, cfg, log, fake).run() == 0
    assert names(project, "blocked") == ["001-thing.md"]
    card = Card(home(project) / "board" / "blocked" / "001-thing.md")
    assert answer.apply(card, answer.questions(card), ["CSV", "out/"])
    from orch.events import Log
    assert Pipeline(project, cfg, Log(project, echo=False), fake).run() == 0
    assert names(project, "done") == ["001-thing.md"] and "-> CSV" in fake.seen and "-> out/" in fake.seen


def test_panel_answer_mode_types_submits_and_requeues(project):
    blocked_card(project)
    ui = tui.UI()
    ui.screen = 2
    ui.col = 3                                                    # Needs you

    def press(*keys):
        for k in keys:
            tui.handle(k, ui, tui.Ctx(project, ui), None)

    press("a")
    assert ui.mode == "answer" and len(ui.qs) == 2
    out = "\n".join(tui.render(project, 2, ui=ui, color=False).split("\n"))
    assert "Answering 001" in out and "question 1 of 2" in out and "Which format?" in out and "▌" in out
    assert {tui.vlen(ln) for ln in out.split("\n")} == {tui.W}
    press(*"quick", "\x7f", "\x7f", "C", "S", "V", "\r")           # 'q' is text here, backspace erases
    assert ui.mode == "answer" and ui.ans == ["quiCSV"]
    press(*"out/", "\r")
    assert ui.mode is None and "queued" in ui.msg
    card = Card(home(project) / "board" / "backlog" / "001-thing.md")
    assert "-> quiCSV" in card.section("Answers") and "-> out/" in card.section("Answers")
    assert card.section("Blockers") == ""


def test_panel_answer_cancel_and_guards(project):
    from conftest import add_card
    add_card(project)                                             # backlog card: nothing to answer
    ui = tui.UI()
    tui.handle("a", ui, tui.Ctx(project, ui), None)
    assert ui.mode is None and "Needs you" in ui.msg
    blocked_card(project, "002-q")
    ui = tui.UI()
    ui.col = 3
    tui.handle("a", ui, tui.Ctx(project, ui), None)
    assert ui.mode == "answer"
    tui.handle("x", ui, tui.Ctx(project, ui), None)
    tui.handle("\x1b", ui, tui.Ctx(project, ui), None)
    assert ui.mode is None and (home(project) / "board" / "blocked" / "002-q.md").exists() and "cancelled" in ui.msg


def test_cli_answer_command(project, monkeypatch, capsys):
    blocked_card(project)
    given = iter(["json", "stdout"])
    monkeypatch.setattr("builtins.input", lambda *_: next(given))
    assert main(["-C", str(project), "answer", "001"]) == 0
    assert "back in the backlog" in capsys.readouterr().out
    assert "-> json" in Card(home(project) / "board" / "backlog" / "001-thing.md").section("Answers")
    assert main(["-C", str(project), "answer"]) == 1                # nothing blocked any more
