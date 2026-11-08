# Contributing

Thanks for helping. This project is small on purpose: standard library only, few files, boring code.

## Setup

```bash
git clone https://github.com/FernandoDevBrito/lonerchestrator.git && cd lonerchestrator
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -e . -r requirements/dev.txt
```

## Before opening a PR

```bash
ruff check .
pytest -q
```

CI runs both on Linux, macOS and Windows with Python 3.10 and 3.12.

## Guidelines

- **No new dependencies.** If the standard library can do it, use it.
- **Every behavior change gets a test.** The pipeline is tested end to end with a fake agent runner and a real temporary git repo (`tests/test_pipeline.py`); follow that pattern. The panel is tested for exact alignment (every screen is exactly 120×34).
- **Platform code lives in `orch/term.py`** (keyboard, processes, window launching). Keep it pure where possible so it can be tested on any OS, and say in the PR which platforms you actually ran it on.
- **Guardrails stay in code**, not in prompts. A rule an agent can ignore is not a guardrail.
- Keep agent protocol markers stable (`RESULT: ...`, `VERDICT: ...`); the pipeline parses them.
- Templates in `orch/templates/` are copied into users' projects: changes there affect every project, mention them in the PR and `CHANGELOG.md`.

## Good first contributions

- Run it on macOS or Linux and report what breaks (or fix it).
- More terminal launchers in `orch/term.py` (`window_command`).
- Tests for edge cases in card parsing and guardrails.
- Translations of the README.

## Reporting bugs

Use the bug template. Include your OS, Python version, `lonerchestrator --help` output, and the relevant lines of `board/_log.md` / `.orchestrator/runs/<run>/events.jsonl` (remove anything private first).

## How the code is organised (where to add things)

Small, explicit extension points instead of long `if` chains. Each one has a test that shows how to use it.

| To add... | Do this | Where |
|---|---|---|
| a step in a card's life (a security scan, a second CI) | write a class with `run(p, job)` returning `PASS`, `retry(text)`, `block(why)` or `APPROVED`, put it in `Pipeline.stages` | `orch/stages.py`, `tests/test_stages.py` |
| an AI that only needs a command line | a `providers` entry in the config, no code | `orch/providers.py` |
| an AI with its own integration | a subclass of `ai.AI` (`call`, `review`, `ask`) | `orch/ai.py` |
| a "Ready to run?" check | a function `check_x(env)` returning `(status, title, hint)` tuples, added to `CHECKS` | `orch/checks.py` |
| a language/tool the project study recognises | a function `detect_x(found)`, added to `DETECTORS` | `orch/scout.py` |
| a web API endpoint | a method decorated `@route("POST", "/api/x", takes="body")` | `orch/web.py`, `web_ais.py`, `web_settings.py` |
| a command | a `cmd_x` function, an entry in `COMMANDS` and a sub-parser | `orch/cli.py` |

Where a card's work lives (the project itself, or a git worktree per card when cards run in parallel) is a *workspace*: `InPlace` in `pipeline.py` and `Hub` in `parallel.py` implement the same `merge`, `park`, `retro` and `lock`. The AI's name and how to get it ready (`name`, `url`, `install_hint`, `login_hint`) live in its preset, so no screen repeats them.

Before a refactor, capture what the code does now (a test, or a before/after comparison on real projects) and keep it green: that is how these were done, one commit each.
