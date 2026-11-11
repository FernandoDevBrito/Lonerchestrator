"""'Ready to run?': what a new user still has to do before the first card can run, with the exact way to fix each item.
Every check is (status, title, hint) with status ok | warn | fail. Pure and cheap enough to refresh every few seconds."""
import json
import os
import re
import shlex
from pathlib import Path

from . import config, folder, providers, scout, trust
from .board import Board
from .gitops import Git

PLACEHOLDER = re.compile(r"<!--.*?-->", re.DOTALL)


def _claude_trusts(project, claude_json):
    """True/False from Claude Code's own trust list, None when it cannot be read. Only the one flag is looked at."""
    try:
        projects = json.loads(Path(claude_json).read_text(encoding="utf-8")).get("projects", {})
    except (OSError, ValueError):
        return None
    want = str(Path(project).resolve()).replace("\\", "/").lower()
    return any(k.replace("\\", "/").lower() == want and v.get("hasTrustDialogAccepted") for k, v in projects.items())


def _ais(project):
    try:
        return json.loads((folder.of(project) / "ais.json").read_text(encoding="utf-8")).get("ais", {})
    except (OSError, ValueError):
        return {}


class Env:
    """What every check may look at: the project, its config, the detected AIs, Claude Code's own config file."""

    def __init__(self, project, claude_json=None):
        self.project = Path(project)
        self.cfg = config.load(self.project)
        self.ais = _ais(self.project)
        self.claude_json = claude_json or os.environ.get("LONERCHESTRATOR_CLAUDE_JSON") or Path.home() / ".claude.json"


# Each check takes an Env and returns a list of (status, title, hint). To add one, write a function and add it to CHECKS.
def check_git(e):
    git = Git(e.project)
    if git.run("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        return [("fail", "Git repository", "run `git init` and make a first commit")]
    base = e.cfg["base"]
    if not git.has_branch(base):
        return [("fail", f"Base branch '{base}'", "pick an existing branch in Settings, or make a first commit (Git tab of the web page)")]
    if not git.clean():
        on = git.branch()
        if on != base:
            return [("warn", f"Uncommitted changes on '{on or 'a detached HEAD'}'", f"switch to '{base}' or commit them: approved cards are merged into '{base}'")]
        return [("ok", f"Git: base '{base}', uncommitted changes", "fine: yours stay as they are. Cards are built from the last commit in "
                 "their own worktree, so the agents do not see them, and land without touching them")]
    return [("ok", f"Git: base '{base}', tree clean", "")]


def check_ais(e):
    """The AIs the roles use (Claude Code, Antigravity, Codex, Gemini, Ollama, or anything defined under `providers`)."""
    reg = providers.registry(e.cfg)
    used = list(dict.fromkeys([r.get("cli", "claude") for r in e.cfg["roles"].values()] + [r["kind"] for r in e.cfg["reviewers"]]))
    out = []
    for pid in used:
        c, name = e.ais.get(pid), reg.get(pid, {}).get("name", pid)
        if pid not in reg:
            out.append(("fail", f"'{pid}' is used by a role but not defined", "pick another AI in the AIs tab, or define it under `providers` in the config"))
        elif not c:
            out.append(("warn", f"{name} not checked yet", "open the AIs tab and press d"))
        elif not c.get("installed"):
            out.append(("fail", f"{name} is not installed", f"run `lonerchestrator ais` to install `{reg[pid]['exe']}`" + (f", or see {reg[pid]['url']}" if reg[pid].get("url") else ", or pick another AI for its roles in the AIs tab")))
        elif not c.get("logged_in"):
            out.append(("fail", f"{name} is not logged in", reg[pid]["login_hint"].replace("then press d", "then press d in the AIs tab")))
        else:
            out.append(("ok", f"{name} ready", ""))
    return out


def check_reviewers(e):
    revs = e.cfg["reviewers"]
    if len({(r["kind"], r.get("model")) for r in revs}) < len(revs):
        return [("warn", "Both reviewers use the same model", "pick different models in the AIs tab: they catch different mistakes")]
    return [("ok", "Two different reviewers", "")]


def check_ci(e):
    try:
        first = shlex.split(folder.render(e.cfg["ci"], folder.of(e.project), e.cfg))
    except ValueError:                                      # unbalanced quotes: the shell will say what is wrong
        first = []
    script = e.project / first[1] if len(first) > 1 and first[0] in ("bash", "sh") else None     # an absolute path stays itself
    if script and not script.is_file():
        return [("fail", f"{first[1]} is missing", "create it (lint + tests + build, exit 1 on failure) or change the CI command in Settings")]
    if not trust.is_trusted(e.project, e.cfg):
        return [("warn", "CI command not approved yet", "press Enter on CI command in Settings, or run `lonerchestrator trust`")]
    return [("ok", "CI command approved", "")]


def check_context(e):
    if not scout.filled(e.project):
        return [("warn", "context/project.md is empty", "run `lonerchestrator context` and the AI studies the repository and fills it (the first run also does it by itself)")]
    return [("ok", "Project context filled in", "")]


def check_claude_folder(e):
    """Claude Code's own folder trust (parent folders do not count). No opinion when its config cannot be read."""
    t = _claude_trusts(e.project, e.claude_json)
    if t is False:
        return [("warn", "Folder not trusted by Claude Code", "run `claude` in this folder once and accept the dialog, or its permissions are ignored")]
    return [("ok", "Folder trusted by Claude Code", "")] if t else []


def check_backlog(e):
    n = len(list((Board(e.project).root / "backlog").glob("*.md")))
    return [("ok", f"{n} card(s) in the backlog", "")] if n else [("warn", "No cards yet", 'add one: `lonerchestrator new "title"`')]


def check_agents(e):
    """Every area's agent needs its role file: Claude Code runs it, every other AI gets its text in the prompt."""
    agents = folder.of(e.project) / "agents"
    missing = sorted({a for a in e.cfg["agents"].values() if not (agents / f"{a}.md").is_file()})
    if not missing:
        return [("ok", f"Agents for every area ({', '.join(config.areas(e.cfg))})", "")]
    return [("warn", "No role file for agent " + ", ".join(missing), f"run `lonerchestrator init` (it adds missing files and keeps yours), or write {agents.as_posix()}/<name>.md")]


CHECKS = [check_git, check_ais, check_reviewers, check_ci, check_context, check_claude_folder, check_agents, check_backlog]


def readiness(project, claude_json=None):
    env = Env(project, claude_json)
    return [item for check in CHECKS for item in check(env)]


def summary(checks):
    """(ready, text): ready only when nothing fails."""
    fails = sum(c[0] == "fail" for c in checks)
    warns = sum(c[0] == "warn" for c in checks)
    return fails == 0, ("ready to run" if not fails and not warns else f"{fails} to fix, {warns} to review" if fails else f"{warns} to review")
