"""Answering the questions an agent left in a blocked card: read them, store the answers in the card, send it back to the backlog.
Used by the panel (Planner tab, key `a`) and by `lonerchestrator answer`."""
import re


def questions(card):
    """The numbered questions under '## Blockers / questions' (a free-text blocker counts as one question)."""
    text = card.section("Blockers")
    qs = []
    for ln in text.splitlines():
        m = re.match(r"\s*(\d+)[.)]\s+(.*)", ln)
        if m:
            qs.append(m.group(2).strip())
        elif qs and ln.strip():
            qs[-1] += " " + ln.strip()
    return qs or ([" ".join(text.split())] if text.strip() else [])


def apply(card, qs, answers):
    """Write the answers into '## Answers' (earlier rounds are kept), clear the questions, reset attempts and requeue the card.
    Returns False (and changes nothing) when every answer is empty."""
    if not any(a.strip() for a in answers):
        return False
    rounds = "\n".join(f"{i}. {q}\n   -> {a.strip() or '(no answer)'}" for i, (q, a) in enumerate(zip(qs, answers, strict=False), 1))
    prev = card.section("Answers")
    card.set_section("Answers", (prev + "\n\n" if prev else "") + rounds)
    card.set_section("Blockers", "")
    card.set("attempts", 0)
    card.log("answered by the user, back to the backlog")
    card.move("backlog")
    return True
