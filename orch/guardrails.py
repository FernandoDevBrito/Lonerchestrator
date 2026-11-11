"""Deterministic guardrails on a card's diff. Violations go back to the builder like a failed review."""
import re
from fnmatch import fnmatch

SECRET = re.compile(
    r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?i:(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"])"
)
TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.)")
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def added_lines(diff):
    """(path, line number in the new file, text) for every added line of a unified diff. Inside a hunk its header says how many lines
    follow, so an added line that itself starts with "++" is still content. A "+" line outside any hunk (a bare fragment) counts too, as
    line 0: this never scans fewer lines than a plain "+" scan."""
    path, n, old, new = "?", 0, 0, 0
    for ln in diff.splitlines():
        if old > 0 or new > 0:
            if ln.startswith("+"):
                yield path, n, ln[1:]
                n, new = n + 1, new - 1
            elif ln.startswith("-"):
                old -= 1
            elif ln.startswith(" ") or not ln:
                n, old, new = n + 1, old - 1, new - 1
            continue                                       # "\ No newline at end of file" counts as nothing
        m = HUNK.match(ln)
        if m:
            old, n, new = int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 1)
        elif ln.startswith("+++ "):
            path = (ln[6:] if ln.startswith("+++ b/") else ln[4:]).rstrip("\t")
        elif ln.startswith("+"):
            yield path, 0, ln[1:]


def check_diff(g, files, deleted, diff):
    v = []
    for f in files:
        if any(fnmatch(f, p) for p in g["protected"]):
            v.append(f"protected path modified (revert it): {f}")
    if len(files) > g["max_files"]:
        v.append(f"{len(files)} files changed, limit {g['max_files']}: split the card")
    lines = sum(1 for ln in diff.splitlines() if ln and ln[0] in "+-" and ln[:3] not in ("+++", "---"))
    if lines > g["max_diff_lines"]:
        v.append(f"{lines} changed lines, limit {g['max_diff_lines']}: split the card")
    if g["forbid_test_deletion"]:
        v += [f"test file deleted: {f}" for f in deleted if TEST_PATH.search(f)]
    if g["scan_secrets"]:                       # where, never what: the line itself would copy the secret into the card and the logs
        v += [f"possible secret in added line: {path}:{n}" if n else f"possible secret in an added line of {path}"
              for path, n, text in added_lines(diff) if SECRET.search(text)]
    return v
