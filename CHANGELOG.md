# Changelog

## 0.1.0 (unreleased)

First public version.

- Pipeline: split, plan (with task list), build, guardrails, CI, parallel independent review, merge, retro.
- Agents: splitter, planner/builder (per area), qa, retro; cross reviewer through the Antigravity CLI or a second Claude model.
- Full-screen panel (120x34): Board, Flow, Planner, Agents, AIs.
- Settings tab: project options editable in the panel (saved at once) and a "Ready to run?" check with the fix for each missing item.
- AIs tab: checklist of allowed AIs/models, role assignment, and live usage (Claude Code account limits: 5-hour and weekly; tokens per model for Claude and agy).
- Answer a blocked card's questions in the panel (Planner tab, key `a`) or with `lonerchestrator answer`; answers go to `## Answers` and agents read them.
- Guardrails in code: protected paths (renames included), size limits, deleted tests, secret scan.
- Security hardening after a review: git hooks/fsmonitor disabled and `.git` tamper detection, terminal-escape sanitization, per-project trust for the CI command (`lonerchestrator trust`), minimal agent permissions. See SECURITY.md.
- Rate-limit backoff, login-expiry abort, per-card artifacts and structured event log.
- `lonerchestrator` command: `init`, `intro`, `new`, `run`, `live`, `tui`, `tail`, `status`.
- Windows, macOS and Linux support (window launching on macOS/Linux is best effort).
- MIT license.
