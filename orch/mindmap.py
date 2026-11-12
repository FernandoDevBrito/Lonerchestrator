"""The Map page: one change as a mind map. The center is what is being done, the branches are where (a card's tasks, or folders), and the
leaves are the changed files with what each changed function or class does.

    work_model(project, guard)              (model, why): your uncommitted work against HEAD as a change-graph model (graph.build)
    build(project, model, title, tasks="")  the map: {"title", "stats", "tasks", "branches": [{"label", "done", "files": [...]}]}
    explain(project, model, sid, ask=None)  one or two sentences on a changed symbol, from the suggester AI

A symbol's text is its own docstring or the comment above it (symbols.docs): free and instant. explain() is one small read-only call, made
only when you ask. Its answer is kept in the project's folder (explained.json) under a hash of the code, so the same code is never asked twice."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from . import folder, graph, groups, symbols
from .gitops import Git
from .usage import _write_atomic
from .view import _json

TASK = re.compile(r"^- \[( |x|X)\] (.+)$", re.MULTILINE)
MAX_LINKS = 12                    # "uses" and "used by" listed per symbol
MAX_CODE = 200                    # lines of a symbol sent to be explained
MAX_SAVED = 500                   # explanations kept per project
_WHO = {f"GIT_{w}_{k}": v for w in ("AUTHOR", "COMMITTER") for k, v in (("NAME", "lonerchestrator"), ("EMAIL", "map@lonerchestrator"),
                                                                          ("DATE", "946684800 +0000"))}      # the same files, the same commit
PROMPT = ("In one or two plain sentences, say what the {kind} `{qual}` in {path} does, for a developer reading a change to it. "
          "Answer with the sentences only: no heading, no list, no code.\n\n```\n{code}\n```")
_CACHE = {}


def work_commit(project):
    """(commit, why): your working tree as a commit on top of HEAD, with tracked changes and the new files .gitignore does not hide. It is
    made with a copy of the index, so your index, branches and files stay as they are. commit is None when there is nothing to show."""
    git = Git(project)
    head = git.run("rev-parse", "-q", "--verify", "HEAD^{commit}", check=False).stdout.strip()
    if not head:
        return None, "This folder has no commit yet."
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, **_WHO, "GIT_INDEX_FILE": str(Path(d) / "index")}
        real = Path(project) / git.out("rev-parse", "--git-path", "index").strip()
        if real.is_file():
            shutil.copyfile(real, env["GIT_INDEX_FILE"])                  # with git's file times in it, only the changed files are read
        git.run("add", "-u", env=env)
        # shortcut: new files over 1 MB stay off the map (adding them copies them into .git/objects); list them if someone misses one
        new = [p for p in git.run("ls-files", "-z", "--others", "--exclude-standard", env=env).stdout.split("\0") if p and _small(project, p)]
        if new:
            git.run("add", "--pathspec-from-file=-", "--pathspec-file-nul", env=env, input="\0".join(new))
        tree = git.run("write-tree", env=env).stdout.strip()
        if tree == git.out("rev-parse", "HEAD^{tree}").strip():
            return None, "Nothing changed since the last commit."
        return git.run("commit-tree", tree, "-p", head, "-m", "lonerchestrator map: the working tree", env=env).stdout.strip(), ""


def _small(project, path):
    try:
        return (Path(project) / path).stat().st_size <= graph.MAX_BYTES
    except OSError:
        return False


def work_model(project, guard=None):
    """(model, why) for your uncommitted work. The model is kept per commit, so asking again for the same files costs only the git calls."""
    commit, why = work_commit(project)
    if commit is None:
        return None, why
    key = (str(project), commit, json.dumps(guard or {}, sort_keys=True))
    if key not in _CACHE:
        if len(_CACHE) > 8:
            _CACHE.clear()
        _CACHE[key] = graph.dumps(graph.build(project, "HEAD", commit, guard=guard, source="worktree"))
    return json.loads(_CACHE[key]), ""


def _side(model, f, s):
    """The "rev:path" of the version a symbol's range is in: the old one for a removed symbol."""
    snap = model["snapshot"]
    return f"{snap['base']}:{f['oldPath'] or f['path']}" if s["range"].get("side") == "old" else f"{snap['head']}:{f['path']}"


def _docs(project, model):
    """{symbol id: its docstring or the comment above it} for the changed symbols, read from the versions of the files the change made."""
    want = {}
    for f in model["files"]:
        if "protected path modified" in f["guardrails"]:
            continue                                                          # graph.py shows no content of a protected file
        for s in f["symbols"]:
            if s["status"] != "context":
                want.setdefault(_side(model, f, s), (f["path"], []))[1].append(s)
    got = graph._cat(Git(project), list(want))
    out = {}
    for name, (path, syms) in want.items():
        found = symbols.docs(path, got.get(name, (None, ""))[0], {0 if s["kind"] == "module" else s["range"]["start"] for s in syms})
        out.update({s["id"]: found[k] for s in syms if (k := 0 if s["kind"] == "module" else s["range"]["start"]) in found})
    return out


def _under(path, p):
    return bool(p) and (path == p or path.startswith(p.rstrip("/") + "/"))


def build(project, model, title, tasks=""):
    """The map of one change (model may be None: nothing changed yet). Branches are the card's tasks, each with the changed files its
    `[files: ...]` names (a file goes to the first task that names it), plus "Other changes"; without such tasks, the folders."""
    todo = []
    for done, text in TASK.findall(tasks):
        m = groups.FILES.search(text)
        todo.append({"text": groups.FILES.sub("", text).strip(), "done": done != " ",
                     "files": [groups.norm(p) for p in m.group(1).split(",")] if m else []})
    files = model["files"] if model else []
    syms = {s["id"]: (f, s) for f in files for s in f["symbols"]}
    docs = _docs(project, model) if model else {}
    links = {}
    for e in model["edges"] if model else []:
        if e["status"] != "removed" and e["from"] in syms and e["to"] in syms:
            for me, other, way in ((e["from"], e["to"], "uses"), (e["to"], e["from"], "usedBy")):
                f, s = syms[other]
                links.setdefault((me, way), []).append({"id": other, "label": s["qual"] or f["path"], "kind": e["kind"]})

    def sym(f, s):
        return {"id": s["id"], "name": "Module level" if s["kind"] == "module" else s["name"], "qual": s["qual"], "kind": s["kind"],
                "status": s["status"], "added": s["added"], "removed": s["removed"], "hot": bool(s.get("hotspot")), "line": s["range"]["start"],
                "old": s["range"].get("side") == "old", "doc": docs.get(s["id"], ""),
                "uses": links.get((s["id"], "uses"), [])[:MAX_LINKS], "usedBy": links.get((s["id"], "usedBy"), [])[:MAX_LINKS]}
    leaves = [{"path": f["path"], "status": f["status"], "added": f["added"], "removed": f["removed"], "note": f["note"],
               "symbols": [sym(f, s) for s in f["symbols"] if s["status"] != "context"]} for f in files if f["status"] != "context"]
    branches = []
    if any(t["files"] for t in todo):
        taken = set()
        for t in todo:
            mine = [x for x in leaves if x["path"] not in taken and any(_under(x["path"], p) for p in t["files"])]
            taken |= {x["path"] for x in mine}
            branches.append({"label": t["text"], "done": t["done"], "files": mine})
        rest = [x for x in leaves if x["path"] not in taken]
        if rest:
            branches.append({"label": "Other changes", "done": None, "files": rest})
    else:
        by_dir = {}
        for x in leaves:
            by_dir.setdefault(x["path"].rsplit("/", 1)[0] if "/" in x["path"] else "Project root", []).append(x)
        branches = [{"label": d, "done": None, "files": xs} for d, xs in sorted(by_dir.items())]
    return {"title": title, "base": model["snapshot"]["base"][:7] if model else "",
            "stats": {"files": len(leaves), "symbols": sum(len(x["symbols"]) for x in leaves),
                      "added": sum(x["added"] for x in leaves), "removed": sum(x["removed"] for x in leaves)},
            "tasks": [{"text": t["text"], "done": t["done"]} for t in todo], "branches": branches}


def code_of(project, model, sid):
    """(path, symbol, code) of a changed symbol (not a module row), possible secrets blanked; None when the change has no such symbol."""
    for f in model["files"]:
        for s in f["symbols"]:
            if s["id"] == sid and s["status"] != "context" and s["kind"] != "module" and "protected path modified" not in f["guardrails"]:
                name = _side(model, f, s)
                text = graph._cat(Git(project), [name]).get(name, (None, ""))[0]
                if text is None:
                    return None
                lines = text.split("\n")[s["range"]["start"] - 1:s["range"]["end"]][:MAX_CODE]
                return f["path"], s, "\n".join(graph.REDACTED if graph.SECRET.search(ln) else ln for ln in lines)
    return None


def explain(project, model, sid, ask=None):
    """One or two plain sentences on what a changed symbol does, from the suggester AI (read-only, the code in the prompt and nothing else).
    None when the symbol is not in the change or the AI did not answer."""
    hit = code_of(project, model, sid)
    if hit is None:
        return None
    path, s, code = hit
    key = hashlib.sha1(f"{path}\n{s['qual']}\n{code}".encode()).hexdigest()
    store = folder.of(project) / "explained.json"
    saved = _json(store)
    if key in saved:
        return saved[key]
    if ask is None:
        from .suggest import asker
        ask = asker(project)
    text = " ".join((ask(PROMPT.format(kind=s["kind"], qual=s["qual"], path=path, code=code)) or "").split())[:600]
    if not text:
        return None
    saved[key] = text
    _write_atomic(store, dict(list(saved.items())[-MAX_SAVED:]))
    return text
