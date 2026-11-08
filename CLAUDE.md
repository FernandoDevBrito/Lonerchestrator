# Orchestrator rules + project context

I (the user) write demand cards in `board/backlog/` (`lonerchestrator new "title"`). Agents plan, implement, review and fix them and stop only when a card is approved or needs me. Everything runs locally on my Claude Code + Antigravity (Gemini) subscriptions: no API keys, no CI service, no servers.

## Project context
Read `context/project.md` (stack, conventions, how to run things) and `context/decisions.md` (why things are the way they are). Keep them current; `context/history.md` is appended by the orchestrator per finished card.

## Flow (`lonerchestrator run`, live view: `lonerchestrator live`)
For each card in `board/backlog/` (priority = filename order):
1. Validate the card structure. SPLIT: the `splitter` agent keeps a normal card whole, or breaks a big one into small child cards (queued in the backlog, run next). Then move to `doing/`, branch `card/<id>` from the base branch.
2. PLAN: area agent writes `## Plan` and a `## Tasks` checklist (each task tied to a criterion and its check). Vague or missing info → `blocked/` with specific questions. Never guess.
3. BUILD: area agent works the tasks (`claude -p --agent <area>`).
4. GUARDRAILS (code, not prompts): protected paths untouched, diff size limits, no deleted tests, no secrets. Violations go back to the builder.
5. CI: the project's `scripts/ci.sh` (lint, tests, build). Failure output goes back to the builder.
6. REVIEW, in parallel, independent: `qa` agent and a Gemini model via `agy`. All must say APPROVED.
7. Rejected → back to the builder with the failures. Max 3 attempts, then `blocked/` as "needs human".
8. Approved → commit, merge into base, card to `done/`, `retro` updates `memory/`, `context/history.md` gets a line.
Never deploy; deploy is a manual command by me. Config: `.orchestrator/config.json`. Logs: `board/_log.md`, `.orchestrator/runs/<run>/events.jsonl` and per-card artifacts.

## Hard rules
- **Quem faz nunca avalia**: the implementer never evaluates its own work. Reviewers see only the card (no plan/tasks/log), the diff and test output, never the implementer's reasoning.
- **3-attempt limit** per card, then `blocked/` for a human.
- **Ask via `blocked/` instead of guessing.**
- Agents do not commit, merge, push, switch branches, or edit `scripts/`, `.claude/`, `CLAUDE.md`, `GEMINI.md`. The orchestrator owns git.
- Stay inside the card's scope; "Out of scope" is binding. One card = one branch.
- Before work read `memory/<area>.md` and `context/`; after work append lessons to `memory/<area>.md`.
- Lazy default (ponytail): stdlib first, fewest files, no unrequested abstractions.

## Agent protocol (machine-read, plain text on its own line)
- Splitter: `RESULT: SINGLE`, `RESULT: SPLIT` or `RESULT: BLOCKED`. Planner/builder: `RESULT: PLANNED`, `RESULT: DONE` or `RESULT: BLOCKED`.
- Reviewers: last line `VERDICT: APPROVED` or `VERDICT: REJECTED`.
