"""Suggested answers on demand: one small Claude call (haiku) that proposes three answers for each question an agent asked.
Used when a blocked card's questions came without suggestions (an older card, or an agent that ignored the format).
The call is read-only: it gets the question text in the prompt and no tools."""
import json
import re
import shutil
import subprocess

from . import usage


def ask_claude(prompt, cwd=None, model="haiku", timeout=120):
    """The text of Claude's reply, or None when it could not be reached (not installed, not logged in, timeout)."""
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "-p", "--verbose", "--output-format", "stream-json", "--model", model, prompt], cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = None
    for ln in p.stdout.splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if ev.get("type") == "rate_limit_event" and ev.get("rate_limit_info"):
            usage.set_claude_limits(ev["rate_limit_info"])
        elif ev.get("type") == "result" and not ev.get("is_error"):
            text = ev.get("result")
    return text if p.returncode == 0 else None


def parse_reply(text, n):
    """[[opt, opt, opt], ...] for n questions from a reply that should be a JSON array of arrays; None when it is not usable."""
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, list) or len(data) != n:
        return None
    out = []
    for opts in data:
        if not isinstance(opts, list):
            return None
        clean = [" ".join(str(o).split()) for o in opts if str(o).strip()][:3]
        if not clean:
            return None
        out.append(clean)
    return out
