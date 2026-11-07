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

    def run(self, *args, check=True):
        r = subprocess.run(["git", *self.pre, *args], cwd=self.cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
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
        r = self.run("merge", "-q", "--no-ff", branch, "-m", msg, check=False)
        if r.returncode:
            self.run("merge", "--abort", check=False)
        return r.returncode == 0

    def ahead(self, base, branch):
        return int(self.out("rev-list", "--count", f"{base}..{branch}").strip() or 0)

    def delete_branch(self, name):
        self.run("branch", "-qd", name, check=False)
