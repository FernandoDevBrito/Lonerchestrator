# Contributing

Thanks for helping. This project is small on purpose: standard library only, few files, boring code.

## Setup

```bash
git clone https://github.com/FernandoDevBrito/lonerchestrator.git && cd lonerchestrator
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -e . pytest ruff
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
