# lonerchestrator

[Português](README.pt-BR.md)

A **local multi-agent orchestrator** for AI coding agents. You write small *cards* describing what you want; agents plan, implement, review and fix them on their own, and only stop when a card is approved or needs a human.

It runs entirely on your machine, on the AI subscriptions you are already logged in to (**Claude Code** and, optionally, the **Antigravity CLI** for Gemini models). No API keys, no hosted service, no GitHub Actions, no server.

```
 card ─▶ SPLIT ─▶ PLAN ─▶ BUILD ─▶ CHECKS ─▶ REVIEW ─▶ MERGE
          │         │        │         │         │         │
      splitter   planner  builder  rules + CI  qa + cross  git + retro
```

| Stage | Who | What happens |
|---|---|---|
| SPLIT | `splitter` agent | Keeps the card whole, or breaks a big one (3+ independent deliverables) into small child cards |
| PLAN | `planner` agent | Writes a plan and a task checklist. If the card is vague it **stops and asks**, it never guesses |
| BUILD | `builder` agent | Implements the tasks and writes the tests |
| CHECKS | code, not prompts | Guardrails (protected files, diff size, secrets, deleted tests) + your `scripts/ci.sh` |
| REVIEW | `qa` + `cross` | Two independent reviewers, ideally on **different models**, in parallel. Both must approve |
| MERGE | git + `retro` agent | Commit, merge into the base branch, record lessons learned |

Core rules: **whoever builds never reviews** (reviewers only see the card, the diff and the test output, never the builder's reasoning); **3 attempts** per card, then it goes to `NEEDS YOU`; it **never deploys**.

> ⚠️ **Read [SECURITY.md](SECURITY.md) first.** The agents edit files and run commands on your machine. Guardrails and a deny-list reduce the risk; they do not remove it. Use it on projects under version control, with a clean working tree.

## Requirements

| | |
|---|---|
| Python | 3.10+ (standard library only, no dependencies) |
| git | any recent version |
| [Claude Code](https://claude.com/claude-code) | installed **and logged in** (`claude`). Required: planner, builder, retro and the `qa` reviewer run on it |
| [Antigravity CLI](https://antigravity.google) `agy` | optional. Gives the `cross` reviewer a Gemini model (a different model family catches different mistakes). Without it, `cross` is a second Claude model |
| bash | to run your project's `scripts/ci.sh` (Git Bash on Windows) |

You need your own Claude Code subscription/login. Usage counts against its limits; the orchestrator waits and retries on rate limits.

### Platforms

| | Panel (`tui`) | New window (`live`) | Notes |
|---|---|---|---|
| Windows 10/11 | ✅ used daily | ✅ Windows Terminal (`wt`) | reference platform |
| macOS | ✅ implemented, CI-tested | ⚠️ Terminal.app via `osascript`, best effort | the panel resizes itself with the xterm resize sequence |
| Linux | ✅ implemented, CI-tested | ⚠️ gnome-terminal, xfce4-terminal, kitty, alacritty, konsole, xterm | needs a graphical session; over SSH use `tui` |

`lonerchestrator tui` works in any terminal of at least **120×34**. Bug reports from macOS/Linux users are very welcome.

## Install

```bash
git clone <repo-url> lonerchestrator && cd lonerchestrator
```

**Windows (PowerShell):**

```powershell
.\install.ps1            # checks requirements, installs the package, makes sure the command is on PATH
.\install.ps1 -DryRun    # show what it would do
```

**macOS / Linux:**

```bash
./install.sh             # uses pipx if available, otherwise pip --user
./install.sh --dry-run
```

Or by hand: `pipx install -e .` / `python -m pip install -e .`. It is an editable install, so `git pull` updates the command. Open a **new terminal** and check:

```bash
lonerchestrator --help
```

Uninstall: `.\install.ps1 -Uninstall` or `./install.sh --uninstall` (your projects, cards and memory are never touched).

## Quick start

```bash
cd your-project            # a git repository, clean working tree
claude                     # once: accept the folder trust dialog, then exit
lonerchestrator init       # installs board, agents, guardrails, context/ and runs the introduction
```

1. **Introduction** (`init`, or `lonerchestrator intro` any time): detects which AIs you are logged in to and lets you choose the model for each role, the two reviewers, and which agent handles each area.
2. Fill in `context/project.md` (stack, how to run tests, conventions) and adapt `scripts/ci.sh` to your project.
3. `lonerchestrator new "Add login"`, then open the card in `board/backlog/` and write a goal and **testable** acceptance criteria.
4. `lonerchestrator` opens the panel. Press `r` to run.

## The panel

Run `lonerchestrator` (no arguments) to open a window at exactly **120×34** with five tabs:

| Tab | Shows |
|---|---|
| **1 Board** | TO DO / DOING / DONE / NEEDS YOU columns with your cards |
| **2 Flow** | The pipeline as connected nodes, with sub-nodes (model, memory, agent, rules) and the latest events |
| **3 Planner** | The selected card: goal, criteria, plan, tasks (`[ ]`/`[x]`), questions for you, history |
| **4 Agents** | What each agent is doing right now, in six aligned live panes |
| **5 AIs** | A checklist of the AIs/models you allow, who does what, and your **live usage** (see below) |

Keys: `←→↑↓` move/select · `1`–`5` or `Tab` switch tab · `PgUp`/`PgDn` scroll · `r` run the pipeline · `x` stop · `q` quit.

### The AIs tab: choose your AIs, watch your usage

- **AIs to use**: every model of the AIs you are logged in to, as a checklist (`↑↓` move, `space` check/uncheck). Unchecking a model that a role uses moves that role to another checked model; you cannot uncheck the last Claude model. Changes are saved to `.orchestrator/config.json` immediately.
- **Who does what**: `splitter`, `planner`, `builder`, `retro` (Claude models) and the two reviewers `qa`/`cross` (any checked AI). `←/→` or `space` changes the model. It warns when both reviewers use the same model.
- **Usage, live**, using only numbers the CLIs really report:
  - **Claude Code**: your account's **5-hour session** and **weekly** limits as bars with the reset time (the same numbers as `/usage`), plus tokens per model for this run and all runs. They update after every agent call; press `u` to refresh on demand (one tiny haiku call).
  - **Antigravity (`agy`)**: tokens per model only. `agy` does not expose remaining quota, and the panel says so instead of inventing a number.
  - The header always shows the compact version, e.g. `claude ● 5h 52% wk 19%   agy ● 18.0k tok`.
- `d` re-detects which AIs you are logged in to.

## Commands

| Command | Does |
|---|---|
| `lonerchestrator` | Open the panel for the project in the current folder (same as `live`) |
| `init [--force]` | Set up a project (never overwrites existing files without `--force`) |
| `intro [--yes]` | Detect logged-in AIs and assign models/agents (`--yes` accepts the defaults) |
| `new "title" [--area frontend\|backend\|both]` | Create a numbered card in `board/backlog/` |
| `run [--card id] [--base branch] [--dry-run]` | Process the backlog headless |
| `live` / `tui` `[--tab 1-5]` | Panel in a new window of the right size / in the current terminal, optionally opened on a tab |
| `tail <role>` | Follow one agent's output (`planner`, `builder`, `qa`, `cross`, `retro`, `pipeline`) |
| `status` | Board counts and latest events |
| `-C <dir>` | (before any command) target another project |

## When a card needs you

Vague cards ("make it faster", "a nice report") are **not implemented**. They go to `NEEDS YOU` with numbered questions under `## Blockers / questions`. Answer by editing the card, move the file from `board/blocked/` back to `board/backlog/`, and run again. Cards that use all 3 attempts end up there too, with the partial work kept on the branch `card/<id>`.

## Guardrails

Checked by **code**, not by prompts, before CI runs:

- protected paths cannot change (`scripts/**`, `.claude/**`, `CLAUDE.md`, `GEMINI.md`, `.orchestrator/**`)
- diff size limits per card (default 25 files / 1000 lines): too-big cards must be split
- deleted tests and secrets in the diff (keys, tokens, passwords) are rejected
- one branch per card (`card/<id>`); nothing merges without both reviewers approving and CI passing
- agents never commit, merge, push or switch branches: the orchestrator owns git
- rate limits: waits with backoff and resumes; an expired login aborts without losing the card
- the project's `.claude/settings.json` allows only what is needed and denies `rm -rf`, `git push`, `git reset --hard`, etc.

## Configuration

`.orchestrator/config.json` in your project (only what you want to change; the rest comes from defaults):

```json
{
  "base": "main",
  "ci": "bash scripts/ci.sh",
  "max_attempts": 3,
  "split": true,
  "verbose": false,
  "roles": { "planner": { "cli": "claude", "model": "sonnet" } },
  "reviewers": [
    { "name": "qa",    "kind": "claude", "agent": "qa", "model": "sonnet" },
    { "name": "cross", "kind": "agy",    "model": "<a model from `agy models`>" }
  ],
  "guardrails": { "max_files": 25, "max_diff_lines": 1000 }
}
```

`base` is the branch that receives approved cards. Point it at a scratch branch to keep `main` untouched until you decide.

## What each project gets

```
your-project/
├── CLAUDE.md  GEMINI.md          orchestrator and reviewer rules
├── board/{backlog,doing,review,done,blocked}/   cards (.md); local, gitignored
├── context/{project,decisions,history}.md       context the agents read
├── memory/{backend,frontend,qa}.md              lessons learned per area (the retro agent maintains it)
├── .claude/{agents,skills,settings.json}        agents and permissions
├── scripts/ci.sh                                your lint + tests + build
└── .orchestrator/                               config, per-run logs, live streams
```

Logs: `board/_log.md` (readable table), `.orchestrator/runs/<run>/events.jsonl` (structured) and, per card, the full text of every agent.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Failed to authenticate` / OAuth expired | Run `claude` (or `agy`) once and log in |
| Permissions in `settings.json` ignored | Folder not trusted: run `claude` inside it and accept the dialog (trusting the parent folder is not enough) |
| "working tree not clean" | Commit or stash first; the orchestrator requires a clean tree |
| "Window too small" | The panel needs 120×34: use `lonerchestrator live` or enlarge the window |
| `gemini` CLI asks you to migrate | Use `agy` (the Antigravity CLI) for Gemini models |
| Pipeline does not start from the panel | Look at `.orchestrator/run.out` |

## Development

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -e . pytest ruff
ruff check . && pytest -q
```

Standard library only. Modules in `orch/`: `pipeline` (the loop), `agents` (CLI runner, backoff), `guardrails`, `board` (cards), `gitops`, `events` (logs), `tui`/`view` (panel), `term` (keyboard/process/window per OS), `intro`, `config`, `cli`. Templates copied by `init` live in `orch/templates/` (`dot-claude/` becomes `.claude/`). See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
