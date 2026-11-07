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
