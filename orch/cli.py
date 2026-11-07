"""lonerchestrator init | new | run | live | tui | intro | tail | status"""
import argparse
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

from . import __version__, aisetup, checks, config, term, trust
from . import answer as answers
from .agents import Runner
from .board import AREAS, Board, create_card
from .events import Log
from .gitops import Git
from .intro import configured, run_intro
from .pipeline import Pipeline
from .safe import clean
from .tui import H, W, run_tui

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"   # shipped inside the package; "dot-" prefix = hidden dir (packaging)
GITIGNORE = ["# orchestrator runtime state", "board/*/*.md", "board/_log.md", ".orchestrator/runs/", ".orchestrator/streams/",
             ".orchestrator/state.json", ".orchestrator/ais.json", ".orchestrator/tui.size", ".orchestrator/run.out", "__pycache__/"]
COLOR = {"pipeline": "37", "planner": "36", "builder": "33", "qa": "35", "cross": "34", "retro": "32"}


def cmd_init(a, project):
    for src in TEMPLATES.rglob("*"):
        dst = project.joinpath(*[".claude" if part == "dot-claude" else part for part in src.relative_to(TEMPLATES).parts])
        if src.is_dir():
            continue
        if dst.exists() and not a.force:
            print(f"keep   {dst.relative_to(project)}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        print(f"write  {dst.relative_to(project)}")
    Board(project).ensure()
    cfg = project / ".orchestrator" / "config.json"
    if not cfg.exists():
        cfg.parent.mkdir(exist_ok=True)
        git = Git(project)
        base = next((b for b in ("main", "master") if git.has_branch(b)), "main")
        cfg.write_text(json.dumps({"base": base, "ci": "bash scripts/ci.sh"}, indent=2) + "\n", encoding="utf-8")
        trust.trust(project, config.load(project))              # we wrote this command ourselves
        print("write  .orchestrator/config.json")
    gi = project / ".gitignore"
    have = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    add = [ln for ln in GITIGNORE if ln not in have]
    if add:
        gi.write_text("\n".join(have + add) + "\n", encoding="utf-8")
    if sys.stdin.isatty():
        run_intro(project)
    print("\nnext: `lonerchestrator intro` (pick AIs/agents) if skipped, fill context/project.md, adjust scripts/ci.sh, then `lonerchestrator new \"title\"` and `lonerchestrator live`")
    return 0


def cmd_intro(a, project):
    return 0 if run_intro(project, assume_yes=a.yes) else 1


def cmd_new(a, project):
    print(create_card(project, a.title, a.area))
    return 0


def cmd_answer(a, project):
    """Answer the questions of a blocked card in the terminal, then send it back to the backlog."""
    blocked = Board(project).cards("blocked")
    pick = [c for c in blocked if a.card and (c.id == a.card or c.id.startswith(a.card))] if a.card else blocked
    if len(pick) != 1:
        print("Blocked cards: " + (", ".join(c.id for c in blocked) or "none") + ("\nGive one id, e.g. `lonerchestrator answer 002`." if blocked else ""))
        return 1
    card = pick[0]
    qs = answers.parse(card)
    if not qs:
        print(f"{card.id} has no questions to answer.")
        return 1
    if answers.missing_options(card):
        print("\nThese questions came without suggested answers: asking Claude for 3 per question (a few seconds)...")
        if answers.add_suggestions(card):
            qs = answers.parse(card)
        else:
            print("(could not get suggestions: you can still write your own answers)")
    print(f"\n{card.title}  ({card.id})\nType 1-3 to pick a suggestion or write your own answer. Leave it empty to skip.\n")
    given = []
    for i, q in enumerate(qs, 1):
        print(f"{i}/{len(qs)}  {q.text}")
        for n, o in enumerate(q.options, 1):
            print(f"       {n}) {o}")
        try:
            given.append(answers.pick(q, input("   > ")))
        except EOFError:
            given.append("")
    if answers.apply(card, qs, given):
        print(f"\nSaved. {card.id} is back in the backlog: run `lonerchestrator run` (or press r in the panel).")
        return 0
    print("\nNo answers given, the card was left as it was.")
    return 1


def ensure_trust(project, cfg):
    """The project's `ci` command runs through a shell: it must be approved once (a cloned repo could ship any command)."""
    if trust.is_trusted(project, cfg):
        return True
    print(f"\nThis project runs this command on your machine for every card:\n\n    {clean(cfg['ci'])}\n\n(from {project / '.orchestrator' / 'config.json'})")
    for pid, p in (cfg.get("providers") or {}).items():
        print(f"and it starts this AI program ('{clean(pid)}'): {clean(' '.join(map(str, p.get('cmd', []))))}")
    if not sys.stdin.isatty():
        print("It is not approved yet. Read it, then run:  lonerchestrator trust")
        return False
    if input("Trust it? [y/N] ").strip().lower() in ("y", "yes", "s", "sim"):
        trust.trust(project, cfg)
        return True
    return False


def cmd_trust(a, project):
    cfg = config.load(project)
    if a.yes:
        trust.trust(project, cfg)
        print(f"trusted: {clean(cfg['ci'])}")
        return 0
    return 0 if ensure_trust(project, cfg) else 1


def cmd_doctor(a, project):
    """Check this machine and, when the current folder is a project, the project too. Exit 1 when something is missing."""
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    tag = {"ok": (" ok ", "32"), "warn": (" !! ", "33"), "fail": (" xx ", "31")}
    bad = []

    def line(status, text, hint=""):
        label, code = tag[status]
        mark = f"\x1b[{code}m[{label}]\x1b[0m" if color else f"[{label}]"
        print(f"  {mark} {text}" + (f"\n         {hint}" if hint else ""))
        if status == "fail":
            bad.append(text)

    print(f"\nlonerchestrator {__version__}  \u00b7  python {platform.python_version()}  \u00b7  {platform.system()}\n")
    py_ok = sys.version_info >= (3, 10)
    line("ok" if py_ok else "fail", f"Python {platform.python_version()}", "" if py_ok else "Python 3.10 or newer is required")
    other = any(shutil.which(e) for e in ("agy", "codex", "gemini"))          # Claude Code is the best tested, but any AI that can edit files will do
    for exe, need, hint in (("git", True, "install it: https://git-scm.com"),
                            ("claude", not other, "run `lonerchestrator ais` to install it, or see https://code.claude.com/docs/en/setup, then run `claude` once to log in"),
                            ("agy", False, "optional: Gemini models. `lonerchestrator ais` installs it"),
                            ("codex", False, "optional: OpenAI Codex. `lonerchestrator ais` installs it"),
                            ("gemini", False, "optional: Gemini CLI. `lonerchestrator ais` installs it"),
                            ("bash", False, "runs the default CI script (scripts/ci.sh); on Windows it comes with Git for Windows")):
        found = term.real_bash() if exe == "bash" else shutil.which(exe)
        wsl = bool(found) and exe == "bash" and "windowsapps" in found.lower()          # only the WSL launcher: no usable bash
        line("ok" if found and not wsl else ("fail" if need else "warn"), f"{exe}" + (f"  ({found})" if found else " not found"),
             "" if found and not wsl else (hint if not found else "that is the WSL launcher, not Git Bash: install Git for Windows, or set another CI command in Settings"))
    system = {"win32": "Windows", "darwin": "Darwin"}.get(sys.platform, "Linux")
    can = term.window_command(system, shutil.which, ["x"], "t", "/", W, H) is not None
    line("ok" if can else "warn", "can open its own window" if can else "cannot open its own window here",
         "" if can else f"`lonerchestrator live` needs a supported terminal; use `lonerchestrator tui` in a terminal of at least {W}x{H}")
    if (project / "board").exists():
        print(f"\n  project: {project}\n")
        for status, title, hint in checks.readiness(project):
            line(status, title, hint)
    else:
        print("\n  no project in this folder. Inside a git repository run:  lonerchestrator init")
    print()
    return 1 if bad else 0


def cmd_ais(a, project):
    """Show which AI CLIs are installed and offer to install the missing ones (always shows the command and asks first)."""
    only = [x.strip().lower() for x in a.install.split(",") if x.strip()] if a.install else None
    return aisetup.run_setup(assume_yes=a.yes, only=only, interactive=sys.stdin.isatty() and sys.stdout.isatty())


def cmd_run(a, project):
    cfg = config.load(project)
    base = a.base or cfg["base"]
    board = Board(project)
    if a.dry_run:
        for c in board.cards("backlog"):
            if a.card in (None, c.id):
                bad = c.problems()
                print(f"[dry-run] {c.id} | area={c.area} agent={cfg['agents'].get(c.area)} | card/{c.id} from {base} | "
                      f"{'INVALID: ' + '; '.join(bad) if bad else 'ok'} | reviewers: {', '.join(r['name'] for r in cfg['reviewers'])}")
        return 0
    if not ensure_trust(project, cfg):
        return 1
    if not Git(project).clean():
        print("working tree not clean; commit or stash first")
        return 1
    log = Log(project)
    jobs = a.jobs or cfg.get("parallel", 1)
    if jobs > 1:                                               # several cards at once, each in its own git worktree
        from .parallel import Parallel
        pipe = Parallel(project, cfg, log, Runner(project, cfg, log), base=base, jobs=jobs)
    else:
        pipe = Pipeline(project, cfg, log, Runner(project, cfg, log), base=base)
    pipe.preflight()
    return pipe.run(a.card)


def cmd_tui(a, project):
    if not ensure_trust(project, config.load(project)):
        return 1
    run_tui(project, a.base or config.load(project)["base"], autorun=a.run, tab=a.tab)
    return 0


def cmd_live(a, project):
    """Open the TUI in a NEW terminal window of exactly the TUI size (Windows Terminal, macOS Terminal, common Linux terminals)."""
    if not (project / "board").exists():
        print(f"{project} is not an orchestrator project yet. Run:  lonerchestrator init")
        return 1
    if not ensure_trust(project, config.load(project)):
        return 1
    if a.setup or not configured(project):
        if run_intro(project, assume_yes=not sys.stdin.isatty()) is None:
            return 1
    proj = str(project)
    dev = ROOT / "bin" / "orch.cmd"            # Windows source checkout: the shim sets PYTHONPATH
    if term.WINDOWS:
        launcher = [str(dev)] if dev.exists() else [sys.executable, "-m", "orch"]
    else:
        launcher = ["env", f"PYTHONPATH={ROOT}", sys.executable, "-m", "orch"]
    argv = [*launcher, "-C", proj, "tui"] + (["--base", a.base] if a.base else []) + (["--run"] if a.run else []) + (["--tab", str(a.tab)] if a.tab != 1 else [])
    if term.open_window(argv, f"lonerchestrator {project.name}", proj, W, H):
        return 0
    print(f"Could not open a terminal window automatically. Run this in a terminal of at least {W}x{H}:\n  lonerchestrator -C {proj} tui")
    return 1


def cmd_tail(a, project):
    f = project / ".orchestrator" / "streams" / f"{a.name}.log"
    c = COLOR.get(a.name, "37")
    sys.stdout.write(f"\x1b[1;{c}m===== {a.name.upper()} =====\x1b[0m\n")
    pos = 0
    try:
        while True:
            if f.exists():
                size = f.stat().st_size
                if size < pos:
                    pos = 0
                if size > pos:
                    with f.open("rb") as h:
                        h.seek(pos)
                        data = h.read()
                    pos += len(data)
                    sys.stdout.write(f"\x1b[{c}m{clean(data.decode('utf-8', 'replace'))}\x1b[0m")
                    sys.stdout.flush()
            time.sleep(0.3)
    except KeyboardInterrupt:
        return 0


def cmd_status(a, project):
    print("board:", ", ".join(f"{k}={v}" for k, v in Board(project).counts().items()))
    st = project / ".orchestrator" / "state.json"
    if st.exists():
        print("state:", st.read_text(encoding="utf-8"))
    log = project / "board" / "_log.md"
    if log.exists():
        print("\nlast events:\n" + "\n".join(log.read_text(encoding="utf-8").splitlines()[-12:]))
    return 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="lonerchestrator")
    ap.add_argument("-C", dest="project", default=".", help="project directory (default: cwd)")
    ap.add_argument("--version", action="version", version=f"lonerchestrator {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("init", help="install board/agents/guardrails into a project")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("new", help="create a card in board/backlog")
    p.add_argument("title")
    p.add_argument("--area", choices=AREAS, default="backend")
    p = sub.add_parser("trust", help="approve the project's CI command (it runs through a shell)")
    p.add_argument("--yes", action="store_true", help="approve without asking")
    p = sub.add_parser("answer", help="answer the questions of a blocked card and send it back to the backlog")
    p.add_argument("card", nargs="?", help="card id or its number, e.g. 002 (optional when only one card is blocked)")
    p = sub.add_parser("run", help="process the backlog (headless)")
    p.add_argument("--card")
    p.add_argument("--base")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-j", "--jobs", type=int, metavar="N", help="work on N cards at the same time (default: `parallel` in the config, 1)")
    p = sub.add_parser("live", help="open the panel in a new terminal window of the right size")
    p.add_argument("--tab", type=int, default=1, choices=range(1, 7), help="open on this tab (1 Board, 2 Flow, 3 Planner, 4 Agents, 5 AIs, 6 Settings)")
    p.add_argument("--base")
    p.add_argument("--run", action="store_true", help="start the pipeline right away")
    p.add_argument("--setup", action="store_true", help="run the introduction first")
    p = sub.add_parser("intro", help="detect logged-in AIs and assign agents/models to roles")
    p.add_argument("--yes", action="store_true", help="accept defaults, no questions")
    p = sub.add_parser("tui", help="full-screen panel: Board | Flow | Planner | Agents | AIs (keyboard)")
    p.add_argument("--tab", type=int, default=1, choices=range(1, 7), help="open on this tab (1 Board, 2 Flow, 3 Planner, 4 Agents, 5 AIs, 6 Settings)")
    p.add_argument("--base")
    p.add_argument("--run", action="store_true", help="start the pipeline right away")
    p = sub.add_parser("tail", help="follow one agent's live stream")
    p.add_argument("name")
    p = sub.add_parser("ais", help="which AI CLIs you have (Claude Code, Antigravity) and install the missing ones")
    p.add_argument("--install", metavar="IDS", help="install these without the menu: claude, agy, or all (comma separated)")
    p.add_argument("--yes", action="store_true", help="run the official installers without asking first")
    sub.add_parser("status")
    sub.add_parser("doctor", help="check this machine (and the project here): what is installed, what is missing, how to fix it")
    a = ap.parse_args(argv)
    if a.cmd is None:                       # bare `lonerchestrator` = open the TUI for this folder
        a = ap.parse_args(["-C", a.project, "live"])
    project = Path(a.project).resolve()
    return globals()[f"cmd_{a.cmd}"](a, project)
