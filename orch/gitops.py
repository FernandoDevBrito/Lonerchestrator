"""Thin git wrapper. The orchestrator owns git; agents never commit, merge, push or switch branches."""
import subprocess


class Git:
    def __init__(self, project):
        self.cwd = str(project)

    def run(self, *args, check=True):
        r = subprocess.run(["git", *args], cwd=self.cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if check and r.returncode:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
        return r

    def out(self, *args):
        return self.run(*args).stdout

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
        return self.out("diff", "--cached", base)

    def changed(self, base, deleted=False):
        flt = ["--diff-filter=D"] if deleted else []
        return [f for f in self.out("diff", "--cached", "--name-only", *flt, base).splitlines() if f]

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
