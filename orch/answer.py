"""Answering the questions an agent left in a blocked card: read them, store the answers in the card, send it back to the backlog.
Used by the panel (Planner tab, key `a`) and by `lonerchestrator answer`.

Agents write every question with three suggested answers, so the user can answer with one key:

    1. Which output format should the report use?
       a) Plain text summary on stdout
       b) CSV file in out/report.csv
       c) Markdown file in out/report.md
"""
import re
from dataclasses import dataclass, field

_Q = re.compile(r"\s*(\d+)[.)]\s+(.*)")
_OPT = re.compile(r"\s+(?:[-*]\s+)?([a-zA-Z])[.)]\s+(.*)")


@dataclass
class Question:
    text: str
    options: list = field(default_factory=list)       # the suggested answers (agents write three)


def parse(card):
    """The numbered questions under '## Blockers / questions', each with its suggested answers. A free-text blocker is one question."""
    text = card.section("Blockers")
    qs = []
    for ln in text.splitlines():
        if (m := _Q.fullmatch(ln)):
            qs.append(Question(m.group(2).strip()))
        elif qs and (m := _OPT.fullmatch(ln)):
            qs[-1].options.append(m.group(2).strip())
        elif qs and ln.strip():                          # a wrapped line belongs to the last option, or to the question itself
            if qs[-1].options:
                qs[-1].options[-1] += " " + ln.strip()
            else:
                qs[-1].text += " " + ln.strip()
    return qs or ([Question(" ".join(text.split()))] if text.strip() else [])


def questions(card):
    return [q.text for q in parse(card)]


def missing_options(card):
    """True when the card has questions but at least one lacks the three suggested answers (the agent ignored the format)."""
    qs = parse(card)
    return bool(qs) and any(len(q.options) < 3 for q in qs)


def render(qs):
    """The questions as they are written in the card: `N. question` followed by `a) b) c)` lines."""
    out = []
    for n, q in enumerate(qs, 1):
        out.append(f"{n}. {q.text}")
        out += [f"   {chr(97 + k)}) {o}" for k, o in enumerate(q.options)]
    return "\n".join(out)


def suggestion_prompt(card, need):
    answers = card.section("Answers")
    qs = "\n".join(f"{n}. {q.text}" for n, q in enumerate(need, 1))
    return (
        "You help a user answer questions that an AI coding agent asked about a software task.\n"
        f"Task: {card.title}\nGoal: {card.section('Goal')}\n"
        + (f"The user already answered earlier:\n{answers}\n" if answers else "")
        + "\nFor each numbered question below, propose exactly THREE short, concrete and different answers the user could pick, the most sensible first. "
        "Never invent facts about the user's files, data or environment: when a fact is needed, offer choices such as "
        "\"create a small sample for me\", \"I will provide it\" or \"skip this part for now\".\n"
        f"Reply with ONLY a JSON array of {len(need)} arrays, one per question in order, each holding three strings. No prose, no markdown.\n\n"
        f"Questions:\n{qs}")


def add_suggestions(card, ask=None):
    """Give every question that lacks three suggested answers its suggestions (one small Claude call for all of them) and save them
    in the card. Returns True when the card was updated, False when nothing was needed or no usable reply came back."""
    qs = parse(card)
    need = [i for i, q in enumerate(qs) if len(q.options) < 3]
    if not need:
        return False
    if ask is None:
        from .suggest import ask_claude as ask
    from .suggest import parse_reply
    got = parse_reply(ask(suggestion_prompt(card, [qs[i] for i in need])), len(need))
    if not got:
        return False
    for i, opts in zip(need, got, strict=True):
        qs[i].options = opts
    card.set_section("Blockers", render(qs))
    return True


def pick(q, typed):
    """What was typed for a question: '1'..'3' choose that suggested answer, anything else is the user's own words."""
    typed = typed.strip()
    if typed.isdigit() and 1 <= int(typed) <= len(q.options):
        return q.options[int(typed) - 1]
    return typed


def apply(card, qs, answers):
    """Write the answers into '## Answers' (earlier rounds are kept), clear the questions, reset attempts and requeue the card.
    Returns False (and changes nothing) when every answer is empty."""
    if not any(a.strip() for a in answers):
        return False
    texts = [q.text if isinstance(q, Question) else q for q in qs]
    rounds = "\n".join(f"{i}. {q}\n   -> {a.strip() or '(no answer)'}" for i, (q, a) in enumerate(zip(texts, answers, strict=False), 1))
    prev = card.section("Answers")
    card.set_section("Answers", (prev + "\n\n" if prev else "") + rounds)
    card.set_section("Blockers", "")
    card.set("attempts", 0)
    card.log("answered by the user, back to the backlog")
    card.move("backlog")
    return True
