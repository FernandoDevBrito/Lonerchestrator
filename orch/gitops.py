"""Thin git wrapper. The orchestrator owns git; agents never commit, merge, push or switch branches.

Hardening: git can execute code that lives inside .git/ (hooks, core.fsmonitor) or in config-defined diff drivers. Agents have write access
to the project, so every git call disables hooks and fsmonitor, diffs never use external drivers, and `internals()` lets the pipeline
detect an agent touching .git/config or a hook."""
import hashlib
import os
import subprocess
from pathlib import Path


class Git:
    def __init__(self, project, hooks=False):
        self.cwd = str(project)
        self.pre = ["-c", "core.fsmonitor=false"] + ([] if hooks else ["-c", f"core.hooksPath={os.devnull}"])

    def run(self, *args, check=True, **kw):
        r = subprocess.run(["git", *self.pre, *args], cwd=self.cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, **kw)
        if check and r.returncode:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
        return r

    def out(self, *args):
        return self.run(*args).stdout

    def internals(self):
        """Fingerprint of what can execute code when git runs: .git/config and every non-sample hook."""
        common = self.run("rev-parse", "--git-common-dir", check=False).stdout.strip() or ".git"
        gd = Path(self.cwd) / common
        h = hashlib.sha256()
        if (gd / "config").is_file():
            h.update((gd / "config").read_bytes())
        hooks = gd / "hooks"
        if hooks.is_dir():
            for f in sorted(hooks.iterdir()):
                if f.is_file() and not f.name.endswith(".sample"):
                    h.update(f.name.encode() + b"\0" + f.read_bytes())
        return h.hexdigest()

    def clean(self):
        return not self.out("status", "--porcelain").strip()

    def status(self, *paths):
        """Every change (staged, unstaged, untracked; each file, not its folder), optionally only under `paths`: [(XY, path, old path of a rename or "")]."""
        parts = self.run("--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths).stdout.split("\0")
        out, i = [], 0
        while i < len(parts):
            e, i = parts[i], i + 1
            if len(e) > 3:
                old = parts[i] if "R" in e[:2] or "C" in e[:2] else ""
                i += bool(old)
                out.append((e[:2], e[3:], old))
        return out

    def branch(self):
        """The checked-out branch ("" when HEAD is detached)."""
        return self.run("symbolic-ref", "-q", "--short", "HEAD", check=False).stdout.strip()

    def commit_paths(self, paths, subject):
        """Commit what changed under `paths` and nothing else: whatever else is staged or edited in this checkout stays as it is.
        Returns the files committed ([] when nothing there had changed)."""
        if not paths:                                  # no paths would mean every change in the checkout
            return []
        files = list(dict.fromkeys(p for _, new, old in self.status(*paths) for p in (new, old) if p))
        spec = [f":(top,literal){f}" for f in files]   # status paths start at the top of the repository; literal: a [ or * in a name is no pattern
        if files:
            self.run("add", "-A", "--", *spec)
            r = self.run("commit", "-q", "-m", subject, "--", *spec, check=False)
            if r.returncode:
                raise RuntimeError("git commit: " + (r.stderr + r.stdout).strip())
        return files

    def exclude(self, pattern):
        """Ignore `pattern` in this checkout through .git/info/exclude: local, never committed, nothing in the project changes."""
        common = self.run("rev-parse", "--git-common-dir", check=False).stdout.strip() or ".git"
        f = Path(self.cwd) / common / "info" / "exclude"
        try:
            have = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
            if pattern not in have:
                f.parent.mkdir(exist_ok=True)
                f.write_text("\n".join(have + [pattern]) + "\n", encoding="utf-8")
        except OSError:
            pass

    def has_branch(self, name):
        return self.run("rev-parse", "-q", "--verify", name, check=False).returncode == 0

    def checkout(self, name, create_from=None):
        self.run("checkout", "-q", *(["-b", name, create_from] if create_from else [name]))

    def merge_base_into_current(self, base):
        r = self.run("merge", "-q", "--no-edit", base, check=False)
        if r.returncode:
            self.run("merge", "--abort", check=False)
        return r.returncode == 0

    def add_all(self):
        self.run("add", "-A")

    def diff_cached(self, base):
        return self.out("diff", "--cached", "--no-ext-diff", "--no-textconv", base)

    def changed(self, base, deleted=False):
        """Paths changed against base. --no-renames: a moved file must show BOTH its old and new path (a rename used to hide the old one)."""
        flt = ["--diff-filter=D"] if deleted else []
        return [f for f in self.out("diff", "--cached", "--name-only", "--no-renames", "--no-ext-diff", "--no-textconv", *flt, base).splitlines() if f]

    def commit(self, subject, body=""):
        self.run("commit", "-q", "-m", subject, *(["-m", body] if body else []))

    def commit_if_dirty(self, subject):
        if not self.clean():
            self.add_all()
            self.commit(subject)

    def merge_no_ff(self, branch, msg):
        """"" when merged, else git's reason. Git refuses before touching anything when the merge would overwrite uncommitted changes."""
        r = self.run("merge", "-q", "--no-ff", branch, "-m", msg, check=False)
        if r.returncode:
            self.run("merge", "--abort", check=False)
        return " ".join((r.stderr or r.stdout or "git merge failed").split())[:400] if r.returncode else ""

    def land(self, branch, base, msg):
        """Merge `branch`, which already contains `base`, into `base` checked out here, around the user's uncommitted work: the merge commit
        (its tree is the branch's) is made first, then `base` fast-forwards to it. Git then updates only the files the branch changed, keeps
        whatever else is staged or edited, and refuses, touching nothing, when one of those files has changes. "" when landed, else why not."""
        here = self.branch()
        if here != base:
            return f"this folder is on '{here or 'a detached HEAD'}', not on '{base}': switch back to '{base}' and send the card again"
        if self.run("merge-base", "--is-ancestor", base, branch, check=False).returncode:     # else its tree would drop newer work on base
            return f"{branch} does not contain the latest {base}: send the card again"
        m = self.out("commit-tree", f"{branch}^{{tree}}", "-p", base, "-p", branch, "-m", msg).strip()
        r = self.run("merge", "-q", "--ff-only", m, check=False)
        return " ".join((r.stderr or r.stdout or "git merge failed").split())[:400] if r.returncode else ""

    def ahead(self, base, branch):
        return int(self.out("rev-list", "--count", f"{base}..{branch}").strip() or 0)

    def delete_branch(self, name):
        self.run("branch", "-qd", name, check=False)
