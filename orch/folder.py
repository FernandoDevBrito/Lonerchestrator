"""Where the orchestrator keeps a project's files: a folder of its own, outside the project.

    ~/.lonerchestrator/projects/<project folder name>-<hash of its path>/      (LONERCHESTRATOR_HOME moves the whole tree)
        config.json  rules.md  settings.json  ci.sh  agents/     what the agents follow (`init` writes them, they are yours to edit)
        board/  context/  memory/                                the cards, what the agents know about the project, what they learned
        runs/  streams/  log.md  state.json  run.out  ...        what happened
        work/<card>/                                             a card that is built in its own git worktree, while it runs
        project.json                                             where the project is and its first commit, to find it again (locate)

The project gets nothing of it: no files, no commits, no .gitignore lines. Losing the project loses none of this: cloned again, in the
same place or another, it gets this folder back."""
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from . import usage
from .gitops import Git

TEMPLATES = Path(__file__).resolve().parent / "templates"
STATES = ("backlog", "doing", "review", "done", "blocked")
OLD_CI = "bash scripts/ci.sh"
OLD_IGNORE = {"# orchestrator runtime state", "board/*/*.md", "board/_log.md", ".orchestrator/runs/", ".orchestrator/streams/",
              ".orchestrator/state.json", ".orchestrator/ais.json", ".orchestrator/tui.size", ".orchestrator/run.out"}


def of(project):
    """The folder of this project (it may not exist yet)."""
    p = Path(project).resolve()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", p.name).strip("-.")[:40] or "project"
    return usage.home() / "projects" / f"{name}-{hashlib.sha1(os.path.normcase(str(p)).encode('utf-8')).hexdigest()[:8]}"


def exists(project):
    """True once `lonerchestrator init` set this project up."""
    return (of(project) / "config.json").is_file()


def render(text, home, cfg):
    """`{ci}` and `{folder}` in an agent's text, the rules, the permissions or a command: the CI command and the folder (forward slashes)."""
    return text.replace("{ci}", cfg["ci"]).replace("{folder}", Path(home).as_posix())


def agent(home, name):
    """(front matter, text) of agents/<name>.md in the folder; ({}, "") when there is no such agent."""
    f = Path(home) / "agents" / f"{name}.md"
    text = f.read_text(encoding="utf-8") if f.is_file() else ""
    if not (text.startswith("---") and text.count("---") >= 2):
        return {}, text.strip()
    _, head, body = text.split("---", 2)
    meta = {k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in head.splitlines()) if v.strip()}
    return meta, body.strip()


def install(project, force=False, say=print):
    """The templates (rules, permissions, CI script, agents, card template, context, memory) copied into the folder. Files already
    there are kept unless `force`. Returns the folder."""
    home = of(project)
    for src in sorted(TEMPLATES.rglob("*")):
        dst = home / src.relative_to(TEMPLATES)
        if src.is_dir() or (dst.exists() and not force):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        say(f"write  {dst.relative_to(home).as_posix()}")
    for s in STATES:
        (home / "board" / s).mkdir(parents=True, exist_ok=True)
    _remember(Path(project).resolve(), home)
    return home


def _info(home):
    """What project.json says about the folder's project: {"path": ..., "first_commits": [...]}, or {}."""
    try:
        return json.loads((Path(home) / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _first_commits(project):
    """The repository's first commit(s): the same in every clone and after a move, unlike its path or its remote's address."""
    try:
        r = Git(project).run("rev-list", "--max-parents=0", "HEAD", check=False)
    except OSError:                                                             # no git, or no such folder
        return []
    return sorted(r.stdout.split()) if r.returncode == 0 else []


def _remember(p, home, roots=None):
    """project.json: where the project is and what it is, so that its folder is found again when it moves (locate)."""
    roots = _first_commits(p) if roots is None else roots
    info = {"path": str(p), "first_commits": roots or _info(home).get("first_commits", [])}       # no commit yet: keep what was known
    if info != _info(home):
        (home / "project.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def _left(d, roots):
    """The folder `d` holds this repository and its project is no longer where it was: the path is gone, or holds another repository."""
    info = _info(d)
    if not info.get("path") or not roots & set(info.get("first_commits", [])):
        return False
    was = Path(info["path"])
    return not was.exists() or not roots & set(_first_commits(was))


def locate(project, say=print):
    """A project that moved (renamed, another drive, cloned again after it was lost) gets its folder back: the one folder that holds the
    same repository (same first commit) and whose project is no longer where it was is renamed for the new place, its approval kept.
    A clone next to its original gets a folder of its own. Returns where the project was before, or None."""
    from . import config, trust
    p, home = Path(project).resolve(), of(project)
    if exists(p):
        if _info(home).get("path") != str(p) or not _info(home).get("first_commits"):
            _remember(p, home)
        return None
    roots = set(_first_commits(p))
    found = [d for d in sorted((usage.home() / "projects").glob("*")) if d.is_dir() and _left(d, roots)] if roots else []
    if len(found) != 1 or home.exists():
        if found:                                                               # never guess between two, never mix two folders
            say(f"this repository's cards, context and memory may be in {', '.join(map(str, found))} (from where it was before): rename "
                f"the one to keep to {home}" + (", after moving away the folder already there" if home.exists() else ""))
        return None
    was = _info(found[0])["path"]
    try:
        os.replace(found[0], home)
    except OSError as e:
        say(f"this project's folder is {found[0]} (from {was}), but it could not be renamed for this place: {e}")
        return None
    cfg = config.load(p)
    if trust.is_trusted(was, cfg):                                              # the same command, approved for this repository before
        trust.trust(p, cfg)
    _remember(p, home, sorted(roots))
    Git(p).run("worktree", "prune", check=False)                                # card worktrees made at the old place are gone with it
    say(f"this project was at {was}: its folder came along ({home}), with its cards, context and memory")
    return was


def _read(f):
    try:
        return f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
    except OSError:
        return ""


def _modern(text):
    """An agent of the old layout, pointed at the folder: its CI command and its context/memory paths."""
    return re.sub(r"`(context|memory)/", r"`{folder}/\1/", text.replace("bash scripts/ci.sh", "{ci}"))


def migrate(project, say=print):
    """Older versions kept the orchestrator's files in the project itself: move them into the folder. Every file is copied first and
    removed from the project only once all of them are in the folder; what is not recognisably the orchestrator's stays where it is.
    The old rules, permissions and template agents go to the folder's old-setup/ (the new ones replace them). Returns what moved."""
    from . import config, trust
    p, home = Path(project).resolve(), of(project)
    old = p / ".orchestrator"
    if not (old / "config.json").is_file() or exists(p):
        return []
    try:
        raw = json.loads((old / "config.json").read_text(encoding="utf-8"))
        cfg = config.merged(dict(raw))
    except (OSError, ValueError, TypeError, AttributeError):
        say(f"{old / 'config.json'} is not valid: fix it, then run again (the orchestrator's files were left where they are)")
        return []
    trusted = trust.is_trusted(p, cfg)
    moves, rewrite = {}, set()
    for f in old.rglob("*"):
        if f.is_file() and f.relative_to(old).parts[0] not in ("worktrees", "config.json"):    # worktrees are git's; config.json is written last
            moves[f] = home / f.relative_to(old)
    b = p / "board"
    for f in [b / "_TEMPLATE.md", b / "_log.md"] + [c for s in STATES for c in sorted((b / s).glob("*.md"))]:
        if f.is_file():
            moves[f] = home / ("log.md" if f.name == "_log.md" and f.parent == b else f.relative_to(p))
    areas = set(cfg["agents"]) | set(cfg["agents"].values()) | {"qa"} | {f.stem for f in (TEMPLATES / "memory").glob("*.md")}
    for f in [p / "context" / n for n in ("project.md", "decisions.md", "history.md")] + [p / "memory" / f"{a}.md" for a in sorted(areas)]:
        if f.is_file():
            moves[f] = home / f.relative_to(p)
    if "# CI gate for this project" in _read(p / "scripts" / "ci.sh"):
        moves[p / "scripts" / "ci.sh"] = home / "ci.sh"
    for f, mark in ((p / "CLAUDE.md", "# Orchestrator rules"), (p / "GEMINI.md", "# Reviewer rules (Gemini)"),
                    (p / ".claude" / "settings.json", "Edit(.orchestrator/**)"), (p / ".claude" / "skills" / "card-workflow" / "SKILL.md", "name: card-workflow")):
        if mark in _read(f):
            moves[f] = home / "old-setup" / f.relative_to(p)
    used = set(cfg["agents"].values()) | {r.get("agent") for r in cfg["reviewers"]}
    for f in sorted((p / ".claude" / "agents").glob("*.md")):
        text = _read(f)
        template = (TEMPLATES / "agents" / f.name).is_file()
        if not (f.stem in used or re.search(r"RESULT: [A-Z]+|VERDICT: [A-Z]+", text) or (template and f"name: {f.stem}" in text and "memory/" in text)):
            continue                                                            # a Claude Code agent of yours, not the orchestrator's
        if template:
            moves[f] = home / "old-setup" / f.relative_to(p)                   # replaced by the new template of the same name
        else:
            moves[f] = home / "agents" / f.name                                 # your own agent for the orchestrator: pointed at the folder
            rewrite.add(moves[f])
    for src, dst in moves.items():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for f in rewrite:
        f.write_text(_modern(f.read_text(encoding="utf-8")), encoding="utf-8")
    t = home / "board" / "_TEMPLATE.md"
    if t in moves.values():                                                     # the card template's hints, for the new layout
        t.write_text(t.read_text(encoding="utf-8").replace(" in .orchestrator/config.json", " in the config")
                     .replace("`bash scripts/ci.sh` passes", "CI passes"), encoding="utf-8")
    ci = home / "ci.sh"
    if ci.is_file():                                                            # it ran from the project's root: now it runs where it is started
        text = ci.read_text(encoding="utf-8").replace('cd "$(dirname "$0")/.."\n', "")
        ci.write_bytes(text.encode("utf-8"))                                    # LF: bash fails on CRLF, which write_text writes on Windows
        if raw.get("ci") == OLD_CI:
            raw.pop("ci")                                                       # the default: the script in the folder
    install(p, say=lambda _: None)                                              # the new rules, permissions and agents
    (home / "config.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")     # last: from now on the folder is the project's
    moves[old / "config.json"] = home / "config.json"
    if trusted:                                                                 # the same script, approved before: still approved
        trust.trust(p, config.load(p))
    left = []
    for src in list(moves) + list((p / "board").glob("*/.gitkeep")):
        try:
            src.unlink()
        except OSError:                                                         # open in another program (Windows): it is in the folder already
            left.append(src.relative_to(p).as_posix())
    for root in (old, p / "board", p / "context", p / "memory", p / "scripts", p / ".claude"):
        for d in sorted((x for x in root.rglob("*") if x.is_dir()), key=lambda x: len(x.parts), reverse=True) + [root]:
            try:
                d.rmdir()                                                       # only empty folders
            except OSError:
                pass
    gi = p / ".gitignore"
    if gi.is_file():
        data = gi.read_bytes()
        lines = data.decode("utf-8").splitlines()
        keep = [ln for ln in lines if ln.strip() not in OLD_IGNORE]
        if keep != lines:                                                       # the file's own line endings: no other line changes
            nl = "\r\n" if b"\r\n" in data else "\n"
            gi.write_bytes("".join(ln + nl for ln in keep).encode("utf-8"))
    say(f"moved the orchestrator's files out of this project ({len(moves)} files: cards, context, memory, config, logs) into {home}"
        + (f"; its old rules, permissions and agents are in {home / 'old-setup'}" if any("old-setup" in d.parts for d in moves.values()) else "")
        + ("; .orchestrator/worktrees stays: git worktrees of unfinished cards" if (old / "worktrees").exists() else "")
        + (f"; could not remove (in use?), delete by hand: {', '.join(left)}" if left else ""))
    return sorted(src.relative_to(p).as_posix() for src in moves)
