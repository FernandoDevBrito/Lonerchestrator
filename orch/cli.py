"""lonerchestrator init | new | run | live | tui | intro | tail | status | graph"""
import argparse
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

from . import __version__, aisetup, checks, config, folder, term, trust
from . import answer as answers
from .agents import Runner
from .board import AREAS, STATES, Board, create_card
from .events import Log
from .gitops import Git
from .intro import configured, run_intro
from .pipeline import Pipeline
from .safe import clean
from .tui import H, W, run_tui

ROOT = Path(__file__).resolve().parent.parent
COLOR = {"pipeline": "37", "planner": "36", "builder": "33", "qa": "35", "cross": "34", "retro": "32"}


def cmd_init(a, project):
    """Set up the project's folder (folder.py): the project itself gets nothing, no file, no commit, no .gitignore line."""
    home = folder.install(project, force=a.force)
    if not (home / "config.json").exists():
        git = Git(project)
        base = next((b for b in ("main", "master") if git.has_branch(b)), "main")
        config.write_raw(project, {"base": base})
        trust.trust(project, config.load(project))              # the CI command is our own script
        print("write  config.json")
    print(f"\nThe orchestrator keeps everything of this project in {home}\n(cards, context, memory, agents, CI script, logs). Nothing was added to {project}.")
    if sys.stdin.isatty():
        run_intro(project)
    print(f"\nnext: `lonerchestrator intro` (pick AIs/agents) if skipped, `lonerchestrator context` (the AI studies your repository and fills "
          f"context/project.md), adjust {(home / 'ci.sh').as_posix()} to your stack, then `lonerchestrator new \"title\"` and `lonerchestrator web`")
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
    home = folder.of(project)
    print(f"\nThis project runs this command on your machine for every card:\n\n    {clean(folder.render(cfg['ci'], home, cfg))}\n\n(from {home / 'config.json'})")
    for pid, p in (cfg.get("providers") or {}).items():
        print(f"and it starts this AI program ('{clean(pid)}'): {clean(' '.join(map(str, p.get('cmd', []))))}")
        if p.get("server") or p.get("env"):          # Claude Code pointed elsewhere: your code goes to that server
            print(f"    Claude Code sends your code to: {clean(str(p.get('server') or (p.get('env') or {}).get('ANTHROPIC_BASE_URL', '(see its env)')))}")
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
                            ("bash", False, "runs the default CI script (ci.sh in the project's folder); on Windows it comes with Git for Windows")):
        found = term.real_bash() if exe == "bash" else shutil.which(exe)
        wsl = bool(found) and exe == "bash" and "windowsapps" in found.lower()          # only the WSL launcher: no usable bash
        line("ok" if found and not wsl else ("fail" if need else "warn"), f"{exe}" + (f"  ({found})" if found else " not found"),
             "" if found and not wsl else (hint if not found else "that is the WSL launcher, not Git Bash: install Git for Windows, or set another CI command in Settings"))
    system = {"win32": "Windows", "darwin": "Darwin"}.get(sys.platform, "Linux")
    can = term.window_command(system, shutil.which, ["x"], "t", "/", W, H) is not None
    line("ok" if can else "warn", "can open its own window" if can else "cannot open its own window here",
         "" if can else f"`lonerchestrator live` needs a supported terminal; use `lonerchestrator tui` in a terminal of at least {W}x{H}")
    if folder.exists(project):
        print(f"\n  project: {project}\n  its folder: {folder.of(project)}\n")
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
                bad = c.problems(config.areas(cfg))
                print(f"[dry-run] {c.id} | area={c.area} agent={cfg['agents'].get(c.area)} | card/{c.id} from {base} | "
                      f"{'INVALID: ' + '; '.join(bad) if bad else 'ok'} | reviewers: {', '.join(r['name'] for r in cfg['reviewers'])}")
        return 0
    if not ensure_trust(project, cfg):
        return 1
    git = Git(project, hooks=cfg.get("git_hooks", False))
    if not git.has_branch(base):
        unborn = not git.has_branch("HEAD")
        print(f"branch '{base}' does not exist" + (" yet: make the first commit (Git tab of `lonerchestrator web`, or `git add -A` and `git commit`), then run again"
                                                    if unborn else ": pick an existing one in Settings"))
        return 1
    on = git.branch()
    if Board(project).cards("backlog"):                       # the agents read context/project.md before every card: study the repository first if it is empty
        from . import scout
        scout.ensure(project)
    git.exclude("__pycache__/")                                # CI leaves these behind: never part of a card's commit
    dirty = not git.clean()
    if dirty and on != base:
        print(f"you have uncommitted changes on {on or 'a detached HEAD'}: switch to {base} (approved cards are merged into it) or commit them, then run again")
        return 1
    log = Log(project)
    if dirty:
        log.say("pipeline", f"you have uncommitted changes: they stay as they are. Each card is built from the last commit of {base} in its own "
                "git worktree (in the project's folder; set `setup` if CI needs installed dependencies) and merged without touching them")
    jobs = a.jobs or cfg.get("parallel", 1)
    if jobs > 1 or dirty:                                      # several cards at once, or your own work in this folder: each card in its own git worktree
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


def cmd_context(a, project):
    """Study the repository and fill context/project.md (stack, how to run/test, conventions) so the agents know the project."""
    from . import scout
    if not folder.exists(project):
        print(f"{project} is not an orchestrator project yet. Run:  lonerchestrator init")
        return 1
    if scout.filled(project) and not a.force:
        print("context/project.md already has content: it is never overwritten. Use --force to draft it again.")
        return 0
    scout.ensure(project, use_ai=not a.basic, force=a.force)
    return 0


def cmd_web(a, project):
    """A kanban page in your browser (this computer only): watch cards move, add requests, answer questions, run/stop."""
    if not folder.exists(project):
        print(f"{project} is not an orchestrator project yet. Run:  lonerchestrator init")
        return 1
    if not ensure_trust(project, config.load(project)):
        return 1
    from .web import run_web
    run_web(project, a.base or config.load(project)["base"], port=a.port, open_browser=not a.no_open)
    return 0


def cmd_live(a, project):
    """Open the TUI in a NEW terminal window of exactly the TUI size (Windows Terminal, macOS Terminal, common Linux terminals)."""
    if not folder.exists(project):
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
    f = folder.of(project) / "streams" / f"{a.name}.log"
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
    st = folder.of(project) / "state.json"
    if st.exists():
        print("state:", st.read_text(encoding="utf-8"))
    log = folder.of(project) / "log.md"
    if log.exists():
        print("\nlast events:\n" + "\n".join(log.read_text(encoding="utf-8").splitlines()[-12:]))
    return 0


def _csv(v):
    return tuple(x.strip() for x in (v or "").split(",") if x.strip())


def cmd_graph(a, project):
    """The change graph of a card: the symbols its diff changed and what uses them or is used by them. Only reads (docs/change-graph.md)."""
    from . import graph, graphview
    cfg = config.load(project)
    ids = sorted({c.id for s in STATES for c in Board(project).cards(s)})
    hits = [i for i in ids if i == a.card] or [i for i in ids if i.startswith(a.card)] or ([a.card] if graph.snapshots(project, a.card) else [])
    if len(hits) != 1:
        print(f"No single card matches '{clean(a.card)}'" + (f": {', '.join(hits)}" if hits else "") + ". Give its id or number, e.g. 002.")
        return 1
    cid, snaps = hits[0], graph.snapshots(project, hits[0])

    def attempt(n):
        keys = [s["key"] for s in snaps if s["attempt"] == n]
        return keys[-1] if keys else None
    tried = ", ".join(sorted({str(s["attempt"]) for s in snaps})) or "none"
    if a.compare:
        x, _, y = a.compare.partition("..")
        if not (x.isdigit() and y.isdigit() and attempt(int(x)) and attempt(int(y))):
            print(f"--compare takes two attempts that have a graph, e.g. 1..2 (attempts with a graph: {tried})")
            return 1
        model = graph.compare(graph.read(project, cid, attempt(int(x))), graph.read(project, cid, attempt(int(y))))
    else:
        if a.attempt and not attempt(a.attempt):
            print(f"{cid} has no graph for attempt {a.attempt} (attempts with a graph: {tried})")
            return 1
        model, _ = graph.load(project, cid, a.base or cfg["base"], cfg["guardrails"], attempt(a.attempt) if a.attempt else None)
    if model is None:
        print(f"{cid} has no change to show yet: no attempt saved a graph, and there is no card/{cid} branch or merge commit.")
        return 1
    model = graph.view(model, only=_csv(a.only), hide=_csv(a.hide), findings=a.findings, guardrails=a.guardrails, focus=a.focus or "", depth=a.depth)
    if a.focus and not model["files"]:
        print(f"nothing called '{clean(a.focus)}' in the graph of {cid}")
        return 1
    if a.tui:
        return _graph_tui(model)
    tty = sys.stdout.isatty() and not a.out
    plain = a.ascii or os.environ.get("TERM") == "dumb"
    width = shutil.get_terminal_size((80, 24)).columns if tty else 80
    if a.format == "ascii" and not a.focus and model["stats"]["symbols"] > 12:
        print("--format ascii draws one symbol and its neighbours: add --focus <name> (or use the tree, the default)")
        return 1
    fmt = {"tree": lambda m: graphview.tree(m, color=tty and not os.environ.get("NO_COLOR"), ascii_only=plain, width=width),
           "ascii": lambda m: "\n\n".join(graphview.ego(m, sid, ascii_only=plain, width=width) for sid in
                                          ([a.focus] if a.focus else [s["id"] for f in m["files"] for s in f["symbols"] if s["status"] != "context"])),
           # printed JSON escapes every non-ASCII character (\uXXXX, still the same data): a file name can hold bidi or C1 controls
           "json": lambda m: json.dumps(m, indent=2, ensure_ascii=not a.out), "mermaid": graphview.mermaid, "dot": graphview.dot, "svg": graphview.svg}
    text = fmt[a.format](model)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {a.out} ({a.format}, {model['stats']['symbols']} symbols)")
    else:
        print(text)
    return 0


def _graph_tui(model):
    """Browse a change graph with the keyboard (graphview.frame draws it): j/k, Enter = the symbol's diff, space folds a file,
    f = only its neighbourhood, / = search, Esc = clear, q = quit."""
    from . import graph, graphview
    if not (sys.stdin.isatty() and sys.stdout.isatty()):             # both: on Windows, stdin from NUL says it is a terminal
        print("--tui needs a terminal; leave it out to print the tree")
        return 1
    st = {"cur": 0, "open": set(), "fold": set(), "focus": "", "query": "", "typing": None}
    out = sys.stdout
    out.write("\x1b[?1049h\x1b[?25l")
    try:
        with term.RawTerminal():
            while True:
                shown = graph.view(model, focus=st["focus"], query=st["query"]) if st["focus"] or st["query"] else model
                sz = shutil.get_terminal_size((100, 30))
                out.write("\x1b[H\x1b[2J" + graphview.frame(shown, st, sz.columns, sz.lines, color=not os.environ.get("NO_COLOR")))
                out.flush()
                keys = []
                while not keys:
                    time.sleep(0.04)
                    keys = term.read_keys()
                rows = graphview.visible(shown, st)
                for k in keys:
                    if st["typing"] is not None:                        # typing a search: Enter applies, Esc drops it
                        if k in ("\r", "\n"):
                            st.update(query=st["typing"], typing=None, cur=0)
                        elif k == "\x1b":
                            st["typing"] = None
                        elif k in ("\x7f", "\x08"):
                            st["typing"] = st["typing"][:-1]
                        elif len(k) == 1 and k.isprintable():
                            st["typing"] += k
                        continue
                    row = rows[st["cur"]] if rows else (0, None, None)
                    if k in ("q", "\x03"):
                        return 0
                    st["cur"] += {"j": 1, "down": 1, "k": -1, "up": -1, "pgdn": sz.lines - 4, "pgup": 4 - sz.lines}.get(k, 0)
                    if k in ("\r", "\n") and row[2] is not None:
                        st["open"] ^= {row[2]["id"]}
                    elif k in ("\r", "\n", " ") and row[1] is not None:
                        st["fold"] ^= {row[1]["id"]}
                    elif k == "f" and row[2] is not None:
                        st.update(focus=row[2]["id"], cur=0)
                    elif k == "/":
                        st["typing"] = ""
                    elif k == "\x1b":
                        st.update(focus="", query="", cur=0)
                    elif k in ("g", "G"):
                        st["cur"] = 0 if k == "g" else len(rows) - 1
    except KeyboardInterrupt:
        return 0
    finally:
        out.write("\x1b[?25h\x1b[?1049l")
        out.flush()


# Every command, spelled out: `lonerchestrator <name>` runs COMMANDS[name](args, project). A test keeps this in step with the cmd_* functions.
COMMANDS = {
    "init": cmd_init,
    "intro": cmd_intro,
    "new": cmd_new,
    "answer": cmd_answer,
    "trust": cmd_trust,
    "doctor": cmd_doctor,
    "ais": cmd_ais,
    "run": cmd_run,
    "tui": cmd_tui,
    "context": cmd_context,
    "web": cmd_web,
    "live": cmd_live,
    "tail": cmd_tail,
    "status": cmd_status,
    "graph": cmd_graph,
}


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="lonerchestrator")
    ap.add_argument("-C", dest="project", default=".", help="project directory (default: cwd)")
    ap.add_argument("--version", action="version", version=f"lonerchestrator {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("init", help="set up the orchestrator for this project, in a folder of its own (nothing is added to the project)")
    p.add_argument("--force", action="store_true", help="write the templates again over the folder's rules, agents and CI script")
    p = sub.add_parser("new", help="create a card in the backlog")
    p.add_argument("title")
    p.add_argument("--area", default="backend", help=f"one of the areas in the config's `agents` (default: {', '.join(AREAS)})")
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
    p = sub.add_parser("context", help="study the project and fill context/project.md (stack, commands, conventions) for the agents")
    p.add_argument("--force", action="store_true", help="draft it again even if the file has content")
    p.add_argument("--basic", action="store_true", help="no AI: write only the facts found in the repository")
    p = sub.add_parser("web", help="kanban board in your browser: watch cards move, add requests in plain words, answer questions")
    p.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: a free one)")
    p.add_argument("--no-open", action="store_true", help="only print the link, do not open the browser")
    p.add_argument("--base")
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
    p = sub.add_parser("graph", help="a card's change graph: the symbols it changed and what uses them (tree, ascii, json, mermaid, dot, svg)")
    p.add_argument("card", help="card id or its number, e.g. 002")
    p.add_argument("--attempt", type=int, metavar="N", help="the graph of attempt N (default: the latest)")
    p.add_argument("--format", default="tree", choices=["tree", "ascii", "json", "mermaid", "dot", "svg"])
    p.add_argument("--focus", metavar="NAME", help="only this symbol (or file path) and its neighbours")
    p.add_argument("--depth", type=int, default=1, metavar="N", help="with --focus: how many edges away (default 1)")
    p.add_argument("--only", metavar="STATUSES", help="e.g. added,modified (also: removed, context)")
    p.add_argument("--hide", metavar="WHAT", help="context and/or tests, e.g. context,tests")
    p.add_argument("--findings", action="store_true", help="only symbols a reviewer flagged")
    p.add_argument("--guardrails", action="store_true", help="only symbols and files with a guardrail hit")
    p.add_argument("--compare", metavar="A..B", help="what changed between two attempts, e.g. 1..2")
    p.add_argument("--out", metavar="FILE", help="write to a file instead of the terminal")
    p.add_argument("--ascii", action="store_true", help="plain characters only (no box drawing)")
    p.add_argument("--tui", action="store_true", help="browse it with the keyboard")
    p.add_argument("--base")
    a = ap.parse_args(argv)
    if a.cmd is None:                       # bare `lonerchestrator` = open the TUI for this folder
        a = ap.parse_args(["-C", a.project, "live"])
    project = Path(a.project).resolve()
    if a.cmd != "ais":
        folder.migrate(project)             # a project set up by an older version: its files move out of it, into its own folder
        folder.locate(project)              # a project that moved (renamed, another drive, cloned again) gets its folder back
    return COMMANDS[a.cmd](a, project)
