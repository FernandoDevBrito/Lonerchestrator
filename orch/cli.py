"""orch init | new | run | live | tail | status"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .agents import Runner
from .board import AREAS, Board
from .events import Log
from .gitops import Git
from .intro import configured, run_intro
from .pipeline import Pipeline
from .tui import H, W, run_tui

ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = ["# orchestrator runtime state", "board/*/*.md", "board/_log.md", ".orchestrator/runs/", ".orchestrator/streams/",
             ".orchestrator/state.json", ".orchestrator/ais.json", ".orchestrator/tui.size", ".orchestrator/run.out", "__pycache__/"]
COLOR = {"pipeline": "37", "planner": "36", "builder": "33", "qa": "35", "cross": "34", "retro": "32"}


def cmd_init(a, project):
    for src in (ROOT / "templates").rglob("*"):
        dst = project / src.relative_to(ROOT / "templates")
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
        print("write  .orchestrator/config.json")
    gi = project / ".gitignore"
    have = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    add = [ln for ln in GITIGNORE if ln not in have]
    if add:
        gi.write_text("\n".join(have + add) + "\n", encoding="utf-8")
    if sys.stdin.isatty():
        run_intro(project)
    print("\nnext: `orch intro` (pick AIs/agents) if skipped, fill context/project.md, adjust scripts/ci.sh, then `orch new \"title\"` and `orch live`")
    return 0


def cmd_intro(a, project):
    return 0 if run_intro(project, assume_yes=a.yes) else 1


def cmd_new(a, project):
    board = Board(project)
    nums = [int(m.group(1)) for s in ("backlog", "doing", "review", "done", "blocked") for c in board.cards(s)
            if (m := re.match(r"(\d+)-", c.id))]
    slug = re.sub(r"[^a-z0-9]+", "-", a.title.lower()).strip("-")[:40]
    dest = board.root / "backlog" / f"{max(nums, default=0) + 1:03d}-{slug}.md"
    t = (project / "board" / "_TEMPLATE.md").read_text(encoding="utf-8")
    t = t.replace("title: <short title>", f"title: {a.title}").replace("area: backend ", f"area: {a.area} ").replace("# <short title>", f"# {a.title}")
    dest.write_text(t, encoding="utf-8")
    print(dest)
    return 0


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
    if not Git(project).clean():
        print("working tree not clean; commit or stash first")
        return 1
    log = Log(project)
    pipe = Pipeline(project, cfg, log, Runner(project, cfg, log), base=base)
    pipe.preflight()
    return pipe.run(a.card)


def cmd_tui(a, project):
    run_tui(project, a.base or config.load(project)["base"], autorun=a.run)
    return 0


def cmd_live(a, project):
    """One Windows Terminal window opened at exactly the TUI size (tabs: Board, Flow, Planner, Agents)."""
    if not shutil.which("wt"):
        print("Windows Terminal (wt) not found; run `orch tui` in a terminal of at least %dx%d" % (W, H))
        return 1
    if not (project / "board").exists():
        print(f"{project} is not an orchestrator project yet. Run:  lonerchestrator init")
        return 1
    if a.setup or not configured(project):
        if run_intro(project, assume_yes=not sys.stdin.isatty()) is None:
            return 1
    orch, proj = str(ROOT / "bin" / "orch.cmd"), str(project)
    args = ["-C", proj, "tui"] + (["--base", a.base] if a.base else []) + (["--run"] if a.run else [])
    # --size is the text area in cells; +0 rows because the tab bar is hidden by --suppressApplicationTitle-less single tab
    subprocess.Popen(["wt", "--size", f"{W},{H}", "-w", "new", "new-tab", "--title", f"orch {project.name}", "-d", proj, "cmd", "/k", orch, *args])
    return 0


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
                    sys.stdout.write(f"\x1b[{c}m{data.decode('utf-8', 'replace')}\x1b[0m")
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
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("init", help="install board/agents/guardrails into a project")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("new", help="create a card in board/backlog")
    p.add_argument("title")
    p.add_argument("--area", choices=AREAS, default="backend")
    p = sub.add_parser("run", help="process the backlog (headless)")
    p.add_argument("--card")
    p.add_argument("--base")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("live", help="open the TUI in a Windows Terminal window of the right size")
    p.add_argument("--base")
    p.add_argument("--run", action="store_true", help="start the pipeline right away")
    p.add_argument("--setup", action="store_true", help="run the introduction first")
    p = sub.add_parser("intro", help="detect logged-in AIs and assign agents/models to roles")
    p.add_argument("--yes", action="store_true", help="accept defaults, no questions")
    p = sub.add_parser("tui", help="full-screen board: Board | Flow | Planner | Agents (keyboard)")
    p.add_argument("--base")
    p.add_argument("--run", action="store_true", help="start the pipeline right away")
    p = sub.add_parser("tail", help="follow one agent's live stream")
    p.add_argument("name")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd is None:                       # bare `lonerchestrator` = open the TUI for this folder
        a = ap.parse_args(["-C", a.project, "live"])
    project = Path(a.project).resolve()
    return globals()[f"cmd_{a.cmd}"](a, project)
