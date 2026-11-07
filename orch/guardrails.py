"""Deterministic guardrails on a card's diff. Violations go back to the builder like a failed review."""
import re
from fnmatch import fnmatch

SECRET = re.compile(
    r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?i:(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"])"
)
TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.)")


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
    if g["scan_secrets"]:
        for ln in diff.splitlines():
            if ln.startswith("+") and not ln.startswith("+++") and SECRET.search(ln):
                v.append(f"possible secret in added line: {ln[:25]}...")
    return v
