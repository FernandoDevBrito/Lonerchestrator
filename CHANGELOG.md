# Changelog

## 0.1.0 (unreleased)

First public version.

- The agents study your project: when `context/project.md` is empty, the first run (or `lonerchestrator context`, or a web button) gathers facts from the repository (languages, manifests, scripts, CI, README, commits; never secrets) and has the `suggester` AI write it, falling back to the facts as they are. Never overwrites a file with content.

- Usage for every AI: tokens read from what each CLI prints (configurable `usage`/`strip_after` per provider), an estimate marked `~` when it prints none, rolling 5h/day/week windows, your own `budgets` (tokens, calls or USD per window, with bars and reset time) and a `price` per provider for estimated cost.
- Web page redesign: one accent, tinted shadows, sentence-case labels, focus rings, dimmed backdrop behind the card drawer, skeleton first load, composed empty states, staggered tab entry, no horizontal overflow on phones. Fixed: panels no longer move by themselves (animations only on kanban cards), what you type in a field survives refreshes, buttons read the fields on screen, dropped cards land at once and stay. Stricter content security policy (no inline scripts).
- Web page: smoother updates (elements are patched in place, moves and new cards are animated, tab changes fade), cards land instantly when dropped.

- `lonerchestrator web`: the whole terminal panel in the browser (local only, token + Host/Origin checks, no dependencies): Board with drag and drop (move, re-queue, reorder by priority), Flow, Planner with answers, live Agents output, AIs with account limits and usage, Settings with readiness. New requests in plain words are understood by the `suggester` AI into a card draft (rule-based fallback).

- Panel key `n`: write a request in plain words, the card is created and the pipeline starts (or picks it up if already running).

- Several builders on one card (`builders`): tasks declare `[files: ...]`, groups with disjoint files are built at the same time in throw-away worktrees and merged; any doubt falls back to one builder.

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
