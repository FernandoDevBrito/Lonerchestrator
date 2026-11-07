# Changelog

## 0.1.0 (unreleased)

First public version.

- Several cards at once (`parallel`, `run -j N`): one git worktree per card, serialized merges and retros, base re-merged and CI re-run when another card landed first, `depends:` in cards, optional `setup` command per worktree.

- Any AI in any role: presets for Claude Code, Antigravity, Codex, Gemini CLI and Ollama, plus any CLI you describe under `providers` in the config. Custom providers need `lonerchestrator trust`. The AIs tab, intro, doctor and installers list them; the suggested answers can come from any AI (`suggester` role). Codex, Gemini and Ollama presets are untested.

- Pipeline: split, plan (with task list), build, guardrails, CI, parallel independent review, merge, retro.
- Agents: splitter, planner/builder (per area), qa, retro; cross reviewer through the Antigravity CLI or a second Claude model.
- Full-screen panel (120x34): Board, Flow, Planner, Agents, AIs.
- `requirements/` folder (what the machine needs, dev tools) and `lonerchestrator ais`: shows which AI CLIs you have and installs the missing ones with their official installers (asks first; installers take `-With`/`--with`).
- One-line installers (`install.ps1` / `install.sh`: uv, else pipx, else pip), `lonerchestrator --version` and `doctor`, and a release workflow for PyPI trusted publishing.
- Windows: the default CI command uses Git for Windows' bash when the first `bash` on PATH is the WSL launcher.
- Settings tab: project options editable in the panel (saved at once) and a "Ready to run?" check with the fix for each missing item.
- AIs tab: checklist of allowed AIs/models, role assignment, and live usage (Claude Code account limits: 5-hour and weekly; tokens per model for Claude and agy).
- Questions that came without suggestions get them on demand (one small read-only haiku call, saved in the card), in the panel and in `lonerchestrator answer`.
- Every question the agents ask comes with 3 suggested answers: press 1, 2 or 3 in the panel (or type 1-3 in `lonerchestrator answer`), or write your own.
- Answer a blocked card's questions in the panel (Planner tab, key `a`) or with `lonerchestrator answer`; answers go to `## Answers` and agents read them.
- Guardrails in code: protected paths (renames included), size limits, deleted tests, secret scan.
- Security hardening after a review: git hooks/fsmonitor disabled and `.git` tamper detection, terminal-escape sanitization, per-project trust for the CI command (`lonerchestrator trust`), minimal agent permissions. See SECURITY.md.
- Rate-limit backoff, login-expiry abort, per-card artifacts and structured event log.
- `lonerchestrator` command: `init`, `intro`, `new`, `run`, `live`, `tui`, `tail`, `status`.
- Windows, macOS and Linux support (window launching on macOS/Linux is best effort).
- MIT license.
