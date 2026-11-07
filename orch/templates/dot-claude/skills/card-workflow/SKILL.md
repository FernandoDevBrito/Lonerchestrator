---
name: card-workflow
description: How to read, plan, block and complete a demand card in board/. Use when working on any card.
---

# Card workflow

- Card = `board/<state>/<id>.md` using `board/_TEMPLATE.md`. Front matter: `title`, `area`, `attempts`.
- Good plan: files to touch, tests to add, and one line per acceptance criterion saying how it is verified.
- Testable criterion = a command or assertion plus the expected result. "Fast", "nice", "clean" without a number or check is NOT testable: block the card and ask for the number.
- Blocker questions: numbered, specific, answerable in one line (e.g. "1. Target rows/sec and on what input size?").
- Markers on their own line at the end of the reply: `RESULT: PLANNED|DONE|BLOCKED` (workers), `VERDICT: APPROVED|REJECTED` (reviewers).
- Lessons go to `memory/<area>.md`: one concrete bullet each, no duplicates.
