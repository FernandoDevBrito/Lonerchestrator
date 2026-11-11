"""The Git tab of the web page, in the spirit of TortoiseGit: what changed in your folder and each file's diff, commit the files you pick,
push, pull and fetch, and the recent history with what is not pushed yet.

A commit takes only the files picked (anything else you staged stays staged). Nothing is changed while a card is being built in this folder
(its card/ branch is checked out) or on a detached HEAD. Your git hooks run only with "Run my git hooks" on, as for every other commit."""
import os
import subprocess
from pathlib import Path

from . import config
from .gitops import Git
from .safe import clean
from .webcore import Bad, route

MAX_FILES = 500                            # changes listed: a commit request names each one it takes
MAX_DIFF, MAX_LINES = 200_000, 3000        # of one file's diff shown: the page draws one element per line
NET_ENV = {"GIT_TERMINAL_PROMPT": "0"}     # a remote asking for a password fails at once instead of waiting on a terminal nobody sees
COLOR = {"new": "added", "added": "added", "deleted": "removed", "conflict": "removed", "renamed": "renamed", "copied": "renamed"}


def kind(xy):
    """What happened to a file, in one word, from its two `git status` letters."""
    if xy == "??":
        return "new"
    if "U" in xy or xy in ("AA", "DD"):
        return "conflict"
    return next((w for k, w in (("D", "deleted"), ("R", "renamed"), ("C", "copied"), ("A", "added")) if k in xy), "modified")


def upstream(g):
    return g.run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False).stdout.strip()


def literal(path):
    """A path from `git status` as a pathspec: from the top of the repository, and a [ or * in a name is no pattern."""
    return f":(top,literal){path}"


class GitApi:
    def _git(self):
        """git at the top of the repository (the paths `git status` gives start there)."""
        r = Git(self.project).run("rev-parse", "--show-toplevel", check=False)
        if r.returncode:
            raise Bad("this folder is not a git repository: run `git init`")
        return Git(r.stdout.strip(), hooks=config.load(self.project).get("git_hooks", False))

    @staticmethod
    def _busy(g):
        """Why the page may not change git now ("" when it may)."""
        on = g.branch()
        if not on:
            return "HEAD is detached: check out a branch first"
        if on.startswith("card/"):
            return f"a card is being built in this folder ({on}): wait until it is merged"
        return ""

    def _writable(self, g):
        why = self._busy(g)
        if why:
            raise Bad(why, 409)

    @staticmethod
    def _net(g, *args):
        """push, pull and fetch: a time limit and no terminal prompt. Returns what git said."""
        try:
            r = g.run(*args, check=False, timeout=180, env={**os.environ, **NET_ENV})
        except subprocess.TimeoutExpired:
            raise Bad(f"git {args[0]} took more than 3 minutes: check the network and your credentials, or run it in a terminal") from None
        said = " ".join(clean(r.stderr + "\n" + r.stdout).split())
        if r.returncode:
            raise Bad(f"git {args[0]} failed: {said[:400]}")
        return said[:300]

    def _push(self, g):
        if upstream(g):
            return self._net(g, "push")
        remotes = g.out("remote").split()
        if not remotes:
            raise Bad("no remote to push to: add one with `git remote add origin <url>`")
        return self._net(g, "push", "-u", "origin" if "origin" in remotes else remotes[0], "HEAD")     # first push: publish this branch

    @route("GET", "/api/git")
    def git_state(self):
        g = self._git()
        on, head = g.branch(), g.has_branch("HEAD")
        up = upstream(g) if on and head else ""
        behind, ahead = (int(n) for n in g.out("rev-list", "--left-right", "--count", f"{up}...HEAD").split()) if up else (0, 0)
        unpushed = set(g.out("rev-list", f"{up}..HEAD").split()) if up else set()
        log = []
        for line in g.out("log", "-n", "30", "--format=%H%x1f%h%x1f%an%x1f%ar%x1f%s").splitlines() if head else []:
            full, short, who, when, subject = (line.split("\x1f") + [""] * 5)[:5]
            log.append({"hash": short, "author": clean(who), "when": when, "subject": clean(subject), "pushed": bool(up) and full not in unpushed})
        changes = g.status()
        return {"branch": on, "base": self.base, "head": head, "upstream": up, "ahead": ahead, "behind": behind, "remotes": g.out("remote").split(),
                "busy": self._busy(g), "hooks": bool(config.load(self.project).get("git_hooks", False)), "log": log, "more": max(0, len(changes) - MAX_FILES),
                "changes": [{"path": p, "kind": kind(xy), "color": COLOR.get(kind(xy), "modified"), "label": clean(p) + (f"  (was {clean(o)})" if o else "")}
                            for xy, p, o in changes[:MAX_FILES]]}

    @route("GET", "/api/git/diff", takes="query")
    def git_diff(self, q):
        g, path = self._git(), q.get("path", "")
        hit = next(((xy, p, o) for xy, p, o in g.status() if path and path in (p, o)), None)    # only a file git lists as changed: no other path is read
        if hit is None:
            raise Bad("that file has no change any more", 404)
        xy, p, o = hit
        f = Path(g.cwd, p)
        if xy == "??" or not g.has_branch("HEAD"):                       # not in git yet: all of it is new
            if f.is_symlink():
                text = f"+symbolic link to {os.readlink(f)}"
            else:
                data = f.read_bytes()[:MAX_DIFF + 1] if f.is_file() else b""
                text = f"new binary file, {f.stat().st_size} bytes" if b"\0" in data[:8000] else "\n".join("+" + ln for ln in data.decode("utf-8", "replace").splitlines())
        else:
            text = g.run("diff", "HEAD", "--no-color", "--no-ext-diff", "--no-textconv", "-M", "--", *[literal(x) for x in (p, o) if x], check=False).stdout
        lines = text[:MAX_DIFF].splitlines()
        return {"path": p, "text": clean("\n".join(lines[:MAX_LINES])), "cut": len(text) > MAX_DIFF or len(lines) > MAX_LINES}

    @route("POST", "/api/git/commit", takes="body")
    def git_commit(self, body):
        g = self._git()
        self._writable(g)
        msg, paths = str(body.get("message", "")).strip(), body.get("paths")
        if not msg:
            raise Bad("write a commit message")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
            raise Bad("pick at least one file")
        if not set(paths) <= {x for _, p, o in g.status() for x in (p, o) if x}:
            raise Bad("some of those files have no change any more: look again", 409)
        try:
            files = g.commit_paths([literal(p) for p in paths], msg[:10000])
        except RuntimeError as e:
            raise Bad(" ".join(clean(str(e)).split())[:500]) from None
        said = f"committed {len(files)} file(s) as {g.out('rev-parse', '--short', 'HEAD').strip()}"
        if body.get("push"):
            try:
                self._push(g)
                said += " and pushed"
            except Bad as e:
                said += f", but the push failed: {e}"
        return {"msg": said}

    @route("POST", "/api/git/push")
    def git_push(self):
        g = self._git()
        self._writable(g)
        return {"msg": "pushed: " + self._push(g)}

    @route("POST", "/api/git/pull")
    def git_pull(self):
        g = self._git()
        self._writable(g)
        if not upstream(g):
            raise Bad("this branch has no upstream yet: Push publishes it")
        return {"msg": "pulled: " + self._net(g, "pull", "--ff-only", "--no-rebase")}     # never a merge commit or a conflict: git refuses instead

    @route("POST", "/api/git/fetch")
    def git_fetch(self):
        g = self._git()
        if not g.out("remote").split():
            raise Bad("no remote: add one with `git remote add origin <url>`")
        self._net(g, "fetch")
        return {"msg": "fetched"}
