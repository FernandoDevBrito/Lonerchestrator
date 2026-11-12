# Requirements

What lonerchestrator needs on your machine. `lonerchestrator doctor` checks every line of this table and tells you how to fix what is missing.

| Requirement | Needed for | Required? | Check | Install |
|---|---|---|---|---|
| Python 3.10+ | running lonerchestrator | only if you install with pipx/pip (uv fetches Python by itself) | `python --version` | https://www.python.org/downloads/ or [uv](https://docs.astral.sh/uv/) |
| git | branches, merges, the whole card flow | yes | `git --version` | https://git-scm.com/downloads |
| **Claude Code** | planner, builder, retro and the `qa` reviewer | **yes** | `claude --version` | Windows: `irm https://claude.ai/install.ps1 \| iex` · macOS/Linux: `curl -fsSL https://claude.ai/install.sh \| bash` |
| **Antigravity CLI** (`agy`) | a Gemini model as the second reviewer (`cross`) | optional | `agy --version` | Windows: `irm https://antigravity.google/cli/install.ps1 \| iex` · macOS/Linux: `curl -fsSL https://antigravity.google/cli/install.sh \| bash` |
| **OpenAI Codex CLI** (`codex`) | OpenAI models in any role. Preset written from the vendor docs, not run by the author | optional (needs Node.js) | `codex --version` | `npm install -g @openai/codex` |
| **Gemini CLI** (`gemini`) | Gemini models in any role. Preset written from the vendor docs, not run by the author | optional (needs Node.js) | `gemini --version` | `npm install -g @google/gemini-cli` |
| **Ollama (local models)** (`ollama`) | free local models. As `ollama`: text only (review, suggest). As `ollama-claude`: Claude Code drives the models that can use tools, so they build too (Ollama 0.14+). Presets from the vendor docs, not run by the author | optional | `ollama --version` | Windows: `irm https://ollama.com/install.ps1 \| iex` · macOS/Linux: `curl -fsSL https://ollama.com/install.sh \| sh` |
| **Grok Build** (`grok`) | xAI's Grok models in any role (SuperGrok or X Premium+ plan, or `XAI_API_KEY`). Preset from the vendor docs, not run by the author | optional | `grok version` | Windows: `irm https://x.ai/cli/install.ps1 \| iex` · macOS/Linux: `curl -fsSL https://x.ai/cli/install.sh \| bash` |
| **GitHub Copilot CLI** (`copilot`) | your Copilot plan's models in any role. Preset from the vendor docs, not run by the author | optional (needs Node.js 22+) | `copilot --version` | `npm install -g @github/copilot` |
| **Cursor CLI** (`cursor-agent`) | your Cursor plan's models in any role. Preset from the vendor docs, not run by the author | optional | `cursor-agent --version` | https://cursor.com/docs/cli/headless |
| **LM Studio** | local models through Claude Code (`lmstudio`), found when its server runs on port 1234 (0.4.1+) | optional | its app | https://lmstudio.ai |
| **An API key** for MiniMax, DeepSeek, Z.ai GLM, Kimi or OpenRouter | their models through Claude Code (`minimax`, `deepseek`, `zai`, `kimi`, `openrouter`), found when `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `MOONSHOT_API_KEY` or `OPENROUTER_API_KEY` is set. Pay-per-use or the vendor's plan, not your Claude subscription | optional | the variable is set | the vendor's console |
| **Any other AI CLI** | anything you describe under `providers` in the project's `config.json` (OpenCode, Aider, a script, ...) | optional | its own | yours: see the README, section "Any AI" |
| bash | your project's CI script (`ci.sh` in the project's folder) | for the default CI command | `bash --version` | Git for Windows includes it |
| A terminal of at least 120x34 | the panel | yes | `lonerchestrator doctor` | Windows Terminal, macOS Terminal, gnome-terminal, kitty, ... |

You also need to be **logged in** to the AIs you use: run `claude` once (and `agy`) and follow the prompts.

## Install the AI CLIs together with lonerchestrator

You do not have to type those install commands yourself:

```bash
lonerchestrator ais                      # shows which AIs you have and offers to install the missing ones (asks first)
lonerchestrator ais --install claude,agy # installs the ones you name (--yes skips the question)
```

The installers can do the same in one go: `install.ps1 -With claude,agy` or `install.sh --with claude,agy`. Without `-With`, they show your AIs at the end and ask.

Every command above is the vendor's own official installer, shown before it runs. Nothing runs without you saying yes (or passing `--yes` / `-With` on purpose).

## Python packages

| File | What it is |
|---|---|
| [`runtime.txt`](runtime.txt) | none: lonerchestrator uses only the standard library |
| [`dev.txt`](dev.txt) | pytest, ruff, build, bandit: for working on lonerchestrator itself (`python -m pip install -e . -r requirements/dev.txt`) |
