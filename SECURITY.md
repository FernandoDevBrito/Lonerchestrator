# Security

## What this tool does to your machine

lonerchestrator launches AI coding agents (Claude Code, optionally the Antigravity CLI) **with permission to edit files and run a limited set of commands in your project**. Treat it like giving a capable but fallible contractor commit-level access to that repository.

## Safety model

Layers, from strongest to weakest:

1. **Code-enforced guardrails** (not prompts): protected paths, diff size limits, deleted-test detection, secret scanning on the diff, clean-tree requirement, one branch per card, orchestrator-owned git (agents cannot commit, merge, push or switch branches).
2. **Per-project permissions**: the generated `.claude/settings.json` allows only test/lint/build and read-only git commands, and denies `rm -rf`, `git push`, `git reset --hard`, `git clean`, `curl`, `wget` and edits to `scripts/`, `.claude/`, `CLAUDE.md`, `GEMINI.md`. Claude Code only honors it after you trust the folder.
3. **Independent review**: two reviewers that never see the builder's reasoning. This catches mistakes, not malice.
4. **Human gates**: nothing is deployed; unclear or repeatedly failing cards stop and wait for you; approved work lands on a base branch you choose (use a scratch branch to keep `main` untouched).

## Known limits

- Agents can still run any command your allow-list permits (for example your test suite), and test code is code. A malicious or prompt-injected card, dependency or file can make tests do harmful things. **Only run cards and repositories you trust.**
- The secret scan is pattern-based and will miss some secrets. Do not rely on it as your only control.
- Card text, repository files and web content read by agents are untrusted input and can contain prompt injection.
- Do not point it at a repository that contains production credentials in the working tree.
- Review the diff before pushing anything merged by the orchestrator. It never pushes for you.

## Recommendations

- Work on a feature/scratch base branch (`"base"` in `.orchestrator/config.json`) and review before merging to `main`.
- Keep the project's `.claude/settings.json` deny-list; add to it rather than removing from it.
- Run on a machine or account without access to production secrets.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's private vulnerability reporting ("Security" tab, "Report a vulnerability") on this repository, with steps to reproduce and the impact you see. We aim to acknowledge reports within a few days.
