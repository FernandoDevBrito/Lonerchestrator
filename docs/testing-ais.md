# Task: test every AI for real, in Docker

**Status: to do.** On 2026-11-12, AI detection was rewritten and new AIs were added: Grok Build, Copilot CLI, Cursor CLI, and Claude Code driving Ollama, LM Studio, MiniMax, DeepSeek, Z.ai GLM, Kimi and OpenRouter. See `CHANGELOG.md` and `context/decisions.md`. Their flags, addresses and model ids come from the vendors' docs. Only Claude Code and Antigravity have been run by the author. Unit tests use fakes, so they prove the logic but not the real CLIs. Until this task is done, the README marks those rows *written from the vendor docs, not run here*.

## Why Docker

Use one throwaway Linux container per AI. The installers run in the container, not on your machine. API keys go in with `-e` and disappear with the container. Your own Claude login and `~/.claude` are never touched.

## Setup (once)

- **Image:** `python:3.12-slim` plus `git`, `bash`, `curl` and Node.js 22 (Codex, Gemini CLI and Copilot CLI install with npm).
- **Mounts:** a checkout of lonerchestrator, plus a small demo project. The demo is a git repo with a `ci.sh` that runs one test and one small card, such as "add a function and its test".
- **Keys:** pass only the key of the AI under test, e.g. `docker run --rm -it -e MINIMAX_API_KEY ...`. A key never goes into `config.json`.
- **Signing in without a browser:**
  - Claude Code: `claude setup-token`, then `CLAUDE_CODE_OAUTH_TOKEN`.
  - Grok: `grok login --device-auth` or `XAI_API_KEY`.
  - Copilot: `COPILOT_GITHUB_TOKEN`.
  - Cursor: `CURSOR_API_KEY`.
  - Gemini CLI: `GEMINI_API_KEY`.
  - Codex: its device login or `OPENAI_API_KEY`.
- **Ollama:** run the official `ollama/ollama` image next to the test container. Containers don't share `localhost`, so point the preset at it in the demo's config: `"providers": {"ollama-claude": {"server": "http://ollama:11434"}}`. This also tests that a config entry overrides a preset. Pull a small model that lists `tools` in `ollama show <model>`, and set `OLLAMA_CONTEXT_LENGTH` to 64k or more on the Ollama container.
- **LM Studio:** it's a desktop app, so test it on a desktop, or from the container against a machine that runs it (`server`).

## For each AI

For every AI, run these steps in order:

1. **Install:** `lonerchestrator ais --install <id> --yes`. This only applies to AIs in the install catalog.
2. **Detect:** run `lonerchestrator intro` or `doctor`. Check it's listed as ready, with the right models and without a `why`. Then sign out or unset the key: it must say what's missing.
3. **Read call:** give it the suggester and both reviewer roles. Run a card and check that the review ends with a `VERDICT:` line and that `git status` shows no change made by the reviewer. The pipeline doesn't block reviewer edits, so read mode must hold on its own.
4. **Edit call:** give it the planner and builder roles. Check that the card gets its `## Plan`, which means the AI can write in the project's folder outside the checkout. Then check the build passes CI and the card is merged.
5. **Usage:** check that `usage.jsonl` books the calls under this AI's id, never under `claude`.

| AI | Steps | Also confirm |
|---|---|---|
| `claude` | 2–5 | `claude auth status` exits 0 when signed in and 1 when not (the docs say so; an older Claude Code may lack it) |
| `agy` | 2–5 | unchanged, a regression check |
| `codex` | 1–5 | `codex login status` exits 0 or non-zero as expected (only third-party docs say so) |
| `gemini` | 1–5 | first real run of this preset |
| `grok` | 1–5 | `--no-auto-update`, `-p`, `-m`, `--always-approve` and `--effort` are accepted. A review without `--always-approve` neither hangs nor edits (otherwise the watchdog stops it after `card_timeout_min`). What `grok models` prints, so a `models_cmd` can be added. Which installer is behind the `grok` you have, since a community CLI uses the same name |
| `copilot` | 1–5 | `-s`, `--no-ask-user`, `--model=`, `--add-dir=` and `--deny-tool=write, shell` are accepted |
| `cursor` | 2–5 | whether the binary is `cursor-agent` or `agent`. Whether `--model` exists (add `model_args` if it does). A review without `--force` changes nothing. Find the official installer for the catalog |
| `ollama` | 1–3 | text only: reviews and suggestions |
| `ollama-claude` | 2–5 | only models with tool support are listed. Ollama 0.14 or newer is required, and an older one should fail clearly |
| `lmstudio` | 2–5 | embedding models are left out of the list |
| `minimax`, `deepseek`, `zai`, `kimi`, `openrouter` | 2–5 | the model ids in the presets still work (vendors rename them). OpenRouter needs your model ids under `providers` |

## Credentials never leave for another server

Run a small logging HTTP server in the container as a custom provider (`"lan": {"native": true, "server": "http://localhost:9000", "models": ["m"]}`). Make one call, then read the request it logged:
- it must carry `Authorization: Bearer none`;
- it must carry no `x-api-key`, even with `ANTHROPIC_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` set in the container;
- the model it asks for must be `m`, never a `claude-*` name.

Before trusting it, `lonerchestrator trust` must show the server's address.

## Out of reach for a Linux container

- Windows-only behaviour needs a Windows machine: the PowerShell installers, and npm CLIs that are `.cmd` files, which only a full path can start (`providers._quick`, `build_argv`).
- The two `install.sh --dry-run` tests in `tests/test_ais.py` fail under Git Bash on Windows, both before and after this change. Run them in the container to see whether they pass on Linux.

## Done when

- Every row passes, or its preset is fixed and the row passes.
- The presets that pass get `"tested": True`, and their README rows (both languages) say *tested*.
- Anything learned that isn't obvious from the code gets a line in `context/decisions.md`.
- This file's status reads **done**, with the date.
