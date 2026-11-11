# Orchestrator rules

I (the user) write demand cards; agents plan, implement, review and fix them and stop only when a card is approved or needs me. Everything runs locally on my AI subscriptions: no API keys, no CI service, no servers.

## Where things are
- The code is the current folder: a git checkout of the project. The card says what to change in it.
- The orchestrator keeps its files for this project outside it, in `{folder}`: the cards, `{folder}/context/` and `{folder}/memory/`. The prompt gives you the path of your card. Never create `board/`, `context/` or `memory/` inside the project.
- The project's CI (lint, tests, build) is `{ci}`. Run it from the current folder.

## Project context
Read `{folder}/context/project.md` (stack, conventions, how to run things) and `{folder}/context/decisions.md` (why things are the way they are). Keep them current; `{folder}/context/history.md` gets a line from the orchestrator for every finished card.

## Flow
For each card in the backlog (priority = filename order):
1. Validate the card structure. SPLIT: the `splitter` agent keeps a normal card whole, or breaks a big one into small child cards (queued in the backlog, run next). Then the card moves to `doing/` and gets a branch `card/<id>` from the base branch.
2. PLAN: the area agent writes `## Plan` and a `## Tasks` checklist (each task tied to a criterion and its check). Vague or missing info → `blocked/` with specific questions. Never guess.
3. BUILD: the area agent works the tasks.
4. GUARDRAILS (code, not prompts): protected paths untouched, diff size limits, no deleted tests, no secrets. Violations go back to the builder.
5. CI: `{ci}`. Failure output goes back to the builder.
6. REVIEW, in parallel, by independent reviewers. All must say APPROVED.
7. Rejected → back to the builder with the failures. After the last attempt, `blocked/` as "needs human".
8. Approved → commit, merge into base, card to `done/`, `retro` updates `{folder}/memory/`, `{folder}/context/history.md` gets a line.
Never deploy; deploy is a manual command by me.

## Cards
- A card is `<board>/<state>/<id>.md` in the format of `<board>/_TEMPLATE.md`. Front matter: `title`, `area`, `attempts`.
- A good plan names the files to touch, the tests to add, and one line per acceptance criterion saying how it is verified.
- A testable criterion is a command or an assertion plus the expected result. "Fast", "nice", "clean" without a number or a check is NOT testable: block the card and ask for the number.
- Blocker questions: numbered, specific, each with exactly three suggested answers (a, b, c: the most sensible first) so I can answer with one key.

## Hard rules
- **Quem faz nunca avalia**: the implementer never evaluates its own work. Reviewers see only the card (no plan/tasks/log), the diff and test output, never the implementer's reasoning.
- **Attempt limit** per card, then `blocked/` for a human.
- **Ask via `blocked/` instead of guessing.**
- Agents do not commit, merge, push, switch branches, or edit `.claude/`, `CLAUDE.md` or `GEMINI.md` in the project. The orchestrator owns git.
- In `{folder}`, agents change only the card they were given, `context/` and `memory/`.
- Stay inside the card's scope; "Out of scope" is binding. One card = one branch.
- Before work read `{folder}/memory/<area>.md` and `{folder}/context/`; after work append lessons to `{folder}/memory/<area>.md` (one concrete bullet each, no duplicates).
- Evidence over memory: a claim about this project points to `path:line`, a command's output or a commit. What you cannot point to, you ask.
- Decisions leave a trail: one line per decision in `{folder}/context/decisions.md` (date, decision, why, card). Areas are the keys of `agents` in the config (default: backend, frontend, both, docs).
- Lazy default (ponytail): stdlib first, fewest files, no unrequested abstractions.

## Agent protocol (machine-read, plain text on its own line, at the end of the reply)
- Splitter: `RESULT: SINGLE`, `RESULT: SPLIT` or `RESULT: BLOCKED`. Planner/builder: `RESULT: PLANNED`, `RESULT: DONE` or `RESULT: BLOCKED`.
- Reviewers: last line `VERDICT: APPROVED` or `VERDICT: REJECTED`.
