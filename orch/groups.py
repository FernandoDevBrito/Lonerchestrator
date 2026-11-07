"""Several builders on ONE card: split the planner's task list into groups that touch different files.

A task declares its files like this:   - [ ] add the endpoint [files: api/users.py, tests/test_users.py] (criterion 1, test_users)
Tasks that share a file go to the same group. If any task has no files, the card is built by a single builder (nothing is guessed)."""
import re

TASK = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)
FILES = re.compile(r"\[files?:\s*([^\]]+)\]", re.IGNORECASE)


def norm(path):
    return path.strip().strip("`'\"").replace("\\", "/").lstrip("./")


def split(tasks_text, max_groups):
    """[(tasks, files)] with 2..max_groups groups of tasks with disjoint files, or None when the card should be built by one builder."""
    if max_groups < 2:
        return None
    tasks = []
    for line in TASK.findall(tasks_text):
        m = FILES.search(line)
        files = {norm(f) for f in m.group(1).split(",") if norm(f)} if m else set()
        if not files:
            return None
        tasks.append((line.strip(), files))
    groups = []                                          # merge tasks that share a file (small lists: a plain loop is enough)
    for text, files in tasks:
        hit = [g for g in groups if g[1] & files]
        merged = ([text], set(files))
        for g in hit:
            merged = (g[0] + merged[0], g[1] | merged[1])
            groups.remove(g)
        groups.append(merged)
    if len(groups) < 2:
        return None
    groups.sort(key=lambda g: -len(g[0]))
    while len(groups) > max_groups:                      # fold the smallest group into the next smallest
        a = groups.pop()
        b = groups.pop()
        groups.append((b[0] + a[0], b[1] | a[1]))
        groups.sort(key=lambda g: -len(g[0]))
    return [(t, sorted(f)) for t, f in groups]
