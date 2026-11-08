"""'Ready to run?': what a new user still has to do before the first card can run, with the exact way to fix each item.
Every check is (status, title, hint) with status ok | warn | fail. Pure and cheap enough to refresh every few seconds."""
import json
import os
import re
from pathlib import Path

from . import config, providers, scout, trust
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
        return json.loads((Path(project) / ".orchestrator" / "ais.json").read_text(encoding="utf-8")).get("ais", {})
    except (OSError, ValueError):
        return {}


def readiness(project, claude_json=None):
    project = Path(project)
    cfg = config.load(project)
    ais = _ais(project)
    out = []

    # git
    git = Git(project)
    if git.run("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        out.append(("fail", "Git repository", "run `git init` and make a first commit"))
    elif not git.has_branch(cfg["base"]):
        out.append(("fail", f"Base branch '{cfg['base']}'", "pick an existing branch in Settings, or make a first commit"))
    elif not git.clean():
        out.append(("warn", "Uncommitted changes", "commit or stash: the orchestrator needs a clean working tree"))
    else:
        out.append(("ok", f"Git: base '{cfg['base']}', tree clean", ""))

    # the AIs the roles use (Claude Code, Antigravity, Codex, Gemini, Ollama, or anything defined under `providers`)
    reg = providers.registry(cfg)
    used = list(dict.fromkeys([r.get("cli", "claude") for r in cfg["roles"].values()] + [r["kind"] for r in cfg["reviewers"]]))
    for pid in used:
        c, name = ais.get(pid), reg.get(pid, {}).get("name", pid)
        if pid not in reg:
            out.append(("fail", f"'{pid}' is used by a role but not defined", "pick another AI in the AIs tab, or define it under `providers` in .orchestrator/config.json"))
        elif not c:
            out.append(("warn", f"{name} not checked yet", "open the AIs tab and press d"))
        elif not c.get("installed"):
            out.append(("fail", f"{name} is not installed", f"run `lonerchestrator ais` to install `{reg[pid]['exe']}`" + (", or see https://claude.com/claude-code" if pid == "claude" else ", or pick another AI for its roles in the AIs tab")))
        elif not c.get("logged_in"):
            out.append(("fail", f"{name} is not logged in", f"run `{reg[pid]['exe']}` in a terminal, log in, then press d in the AIs tab"))
        else:
            out.append(("ok", f"{name} ready", ""))

    # reviewers
    revs = cfg["reviewers"]
    if len({(r["kind"], r.get("model")) for r in revs}) < len(revs):
        out.append(("warn", "Both reviewers use the same model", "pick different models in the AIs tab: they catch different mistakes"))
    else:
        out.append(("ok", "Two different reviewers", ""))

    # CI command
    first = cfg["ci"].split()
    script = project / first[1] if len(first) > 1 and first[0] in ("bash", "sh") else None
    if script and not script.is_file():
        out.append(("fail", f"{first[1]} is missing", "create it (lint + tests + build, exit 1 on failure) or change the CI command in Settings"))
    elif not trust.is_trusted(project, cfg):
        out.append(("warn", "CI command not approved yet", "press Enter on CI command in Settings, or run `lonerchestrator trust`"))
    else:
        out.append(("ok", "CI command approved", ""))

    # context for the agents
    if not scout.filled(project):
        out.append(("warn", "context/project.md is empty", "run `lonerchestrator context` and the AI studies the repository and fills it (the first run also does it by itself)"))
    else:
        out.append(("ok", "Project context filled in", ""))

    # Claude Code's own folder trust (parent folders do not count)
    t = _claude_trusts(project, claude_json or os.environ.get("LONERCHESTRATOR_CLAUDE_JSON") or Path.home() / ".claude.json")
    if t is False:
        out.append(("warn", "Folder not trusted by Claude Code", "run `claude` in this folder once and accept the dialog, or its permissions are ignored"))
    elif t:
        out.append(("ok", "Folder trusted by Claude Code", ""))

    # something to do
    n = len(list((project / "board" / "backlog").glob("*.md")))
    out.append(("ok", f"{n} card(s) in the backlog", "") if n else ("warn", "No cards yet", 'add one: `lonerchestrator new "title"`'))
    return out


def summary(checks):
    """(ready, text): ready only when nothing fails."""
    fails = sum(c[0] == "fail" for c in checks)
    warns = sum(c[0] == "warn" for c in checks)
    return fails == 0, ("ready to run" if not fails and not warns else f"{fails} to fix, {warns} to review" if fails else f"{warns} to review")
