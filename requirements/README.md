# Requirements

What lonerchestrator needs on your machine. `lonerchestrator doctor` checks every line of this table and tells you how to fix what is missing.

| Requirement | Needed for | Required? | Check | Install |
|---|---|---|---|---|
| Python 3.10+ | running lonerchestrator | only if you install with pipx/pip (uv fetches Python by itself) | `python --version` | https://www.python.org/downloads/ or [uv](https://docs.astral.sh/uv/) |
| git | branches, merges, the whole card flow | yes | `git --version` | https://git-scm.com/downloads |
| **Claude Code** | planner, builder, retro and the `qa` reviewer | **yes** | `claude --version` | Windows: `irm https://claude.ai/install.ps1 \| iex` · macOS/Linux: `curl -fsSL https://claude.ai/install.sh \| bash` |
| **Antigravity CLI** (`agy`) | a Gemini model as the second reviewer (`cross`) | optional | `agy --version` | Windows: `irm https://antigravity.google/cli/install.ps1 \| iex` · macOS/Linux: `curl -fsSL https://antigravity.google/cli/install.sh \| bash` |
| bash | your project's CI script (`scripts/ci.sh`) | for the default CI command | `bash --version` | Git for Windows includes it |
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
