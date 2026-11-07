# Security

## What this tool does to your machine

lonerchestrator launches AI coding agents (Claude Code, optionally the Antigravity CLI) **with permission to edit files and run a limited set of commands in your project**, and it runs your project's CI command through a shell. Treat it like giving a capable but fallible contractor commit-level access to that repository.

## What is trusted and what is not

| Trusted | Untrusted (can be hostile) |
|---|---|
| You, and the code of this tool | Card text, repository files, dependencies, web content an agent reads |
| Your project's `ci` command **after you approved it** | A `.orchestrator/config.json` that came with a repository you cloned |
| The `claude` / `agy` CLIs | Everything an agent writes: files, plans, questions, log output |

## Safety layers

1. **Code-enforced guardrails** (not prompts): protected paths, diff size limits, deleted-test detection, secret scan on the diff, clean-tree requirement, one branch per card.
2. **The orchestrator owns git.** Agents cannot commit, merge, push or switch branches (denied in the generated permissions). Every git call also runs with hooks and `core.fsmonitor` disabled, and diffs never use external/textconv drivers. Your own hooks are skipped on the orchestrator's commits unless you set `"git_hooks": true`.
3. **Tamper detection for `.git`.** `.git/config` and every git hook are fingerprinted before and after every agent call. If an agent changed one, the run aborts at once, before any further git command, and the card goes to Needs you.
4. **Minimal agent permissions.** The generated `.claude/settings.json` allows only the test/lint/compile commands and read-only git, and denies interpreters (`python -c`, `bash -c`, `powershell`, ...), network tools, `git config/add/commit/push`, and edits to `scripts/`, `.claude/`, `.git/`, `.orchestrator/`, `CLAUDE.md`, `GEMINI.md`. Claude Code only honors it after you trust the folder.
5. **Trust gate for the CI command.** `ci` runs through a shell, so each project must be approved once per exact command (`lonerchestrator trust`, or the prompt the first time you open the panel or run it). A changed command needs approval again. `init` trusts only the config it wrote itself, never one that shipped with a cloned repository.
6. **Terminal safety.** Anything that comes from cards, files or agent output is stripped of control characters (ESC, BEL, CR, C1, bidi overrides) before it reaches your screen, and the panel lets only its own color codes through. A card cannot change your window title, clear the screen, spoof the UI or write your clipboard.
7. **Independent review and human gates.** Two reviewers that never see the builder's reasoning. Nothing is deployed; unclear or repeatedly failing cards stop and wait for you; approved work lands on a base branch you choose.

## Findings from the security review (all fixed, each pinned by a test)

| Finding | Severity | Fix |
|---|---|---|
| Moving a protected file (`scripts/ci.sh` to another folder) raised no guardrail violation: git hides the old path on a rename | High | Diffs use `--no-renames`, so both paths are checked |
| Card text and agent output reached the terminal raw (escape sequences, OSC, bidi override) | High | Sanitized at the source and again on every screen line |
| An agent could plant a git hook or change `.git/config` (`core.fsmonitor`) and get code run by the orchestrator's own git calls | High | Hooks/fsmonitor disabled, `.git` fingerprinted around every agent call, `.git/**` denied |
| `ci` from a cloned repo's config ran through a shell with no approval | High | Per-project trust gate |
| Generated permissions allowed a bare `python`, which bypassed the deny-list, plus `agy` and the app entry point | Medium | Allow-list reduced to explicit commands; interpreter flags denied |
| CI workflow ran with the default token permissions | Low | `permissions: contents: read` |

Secret scan of the full git history: nothing found. Static analysis (bandit): one high item, the intentional `shell=True` for the CI command, now behind the trust gate; the rest are low-severity notes about calling `git`/CLIs with argument lists (no shell).

## Known limits (what this does NOT protect you from)

- `lonerchestrator web` serves a page on `127.0.0.1` only. It needs the random token from the link it prints, checks the Host and Origin headers, and shows server text only as text. Anyone who can use your computer's loopback (other local users on a shared machine) and gets the link can drive it: do not share the link and stop the command when you are done.

- With `parallel` above 1, agents of different cards run at the same time in separate git worktrees. They are separated by folder, not by a sandbox: an agent can still reach files outside its worktree if its AI allows it. The `.git` tamper check and the diff guardrails apply to every card. The optional `setup` command runs through a shell and is part of the trust approval.

- **`.claude/settings.json` only restricts Claude Code.** Other AIs (Codex, Gemini, your own `providers`) are limited by the flags in their provider (`edit_args`, `read_args`), plus the diff guardrails, the `.git` tamper check and the reviewers. Read a provider before trusting it; a provider defined in a project's config runs a program and needs `lonerchestrator trust`.
- The Codex, Gemini and Ollama presets were written from the vendors' documentation and have not been run by the author.

- **Tests and project code are code.** The allowed `pytest`/CI commands run whatever the project contains; a hostile card, dependency or test file can make them do harmful things. Only run cards and repositories you trust.
- **Prompt injection is not solved.** Cards, repository files and web pages read by agents can steer them, within the permissions above. The guardrails limit the damage; they cannot read intent.
- **Ignored files are invisible to the diff guardrails.** An agent can still write inside the project to paths that git ignores (for example a virtual environment). Do not point the tool at a repository that holds production credentials in its working tree.
- The secret scan is pattern-based and misses some secrets. It is a safety net, not a control.
- On Windows, the new-window launcher passes the project path to `cmd /k`; a project folder whose name contains shell metacharacters (`&`, `^`) should be renamed.
- Review the diff before pushing anything merged by the orchestrator. It never pushes for you.

## Recommendations

- The on-demand "suggested answers" call is read-only: no agent, no edit permission, only the question text in the prompt, so it cannot change your files.
- `lonerchestrator ais` can run the vendors' official installers (Claude Code, Antigravity). It always shows the command first and asks, unless you pass `--yes` or `-With` on purpose.
- Piping an installer into your shell (`irm ... | iex`, `curl ... | bash`) means trusting it. The scripts are short and in this repository: read them, or run them with `-DryRun` / `--dry-run` first. They use no admin rights or sudo.
- Work on a feature/scratch base branch (`"base"` in `.orchestrator/config.json`) and review before merging to `main`.
- Read the `ci` command before approving it. Keep the deny-list; add to it rather than removing from it.
- Run on a machine or account without access to production secrets.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's private vulnerability reporting ("Security" tab, "Report a vulnerability") on this repository, with steps to reproduce and the impact you see. We aim to acknowledge reports within a few days.
