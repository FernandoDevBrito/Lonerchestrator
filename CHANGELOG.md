# Changelog

## 0.1.0 (unreleased)

First public version.

- Pipeline: split, plan (with task list), build, guardrails, CI, parallel independent review, merge, retro.
- Agents: splitter, planner/builder (per area), qa, retro; cross reviewer through the Antigravity CLI or a second Claude model.
- Full-screen panel (120x34): Board, Flow, Planner, Agents.
- Guardrails in code: protected paths, size limits, deleted tests, secret scan.
- Rate-limit backoff, login-expiry abort, per-card artifacts and structured event log.
- `lonerchestrator` command: `init`, `intro`, `new`, `run`, `live`, `tui`, `tail`, `status`.
- Windows, macOS and Linux support (window launching on macOS/Linux is best effort).
- MIT license.
