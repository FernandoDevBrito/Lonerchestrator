"""Runs the agent CLIs (claude, agy) headless, streams their output live, retries on rate limits."""
import json
import re
import shutil
import subprocess
import time

from .usage import Usage

RATE = re.compile(r"rate.?limit|quota|usage limit|too many requests|\b429\b|resource.?exhausted|overloaded|limit reached", re.IGNORECASE)
AUTH = re.compile(r"oauth|failed to authenticate|not logged in|please (run )?/?login|invalid api key", re.IGNORECASE)


class AuthError(Exception):
    pass


class RateLimitExhausted(Exception):
    pass


def is_rate_limited(raw):
    """Claude emits a rate_limit_event on every call (status 'allowed' normally): only a non-allowed status counts,
    plus any other output that looks like a limit message."""
    rest = []
    for ln in raw.splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            rest.append(ln)
            continue
        if isinstance(ev, dict) and ev.get("type") == "rate_limit_event":
            if (ev.get("rate_limit_info") or {}).get("status", "allowed") not in ("allowed", "allowed_warning"):
                return True
        else:
            rest.append(ln)
    return bool(RATE.search("\n".join(rest)))


def marker(text):
    m = re.findall(r"^RESULT: (PLANNED|DONE|BLOCKED|SINGLE|SPLIT)", text, re.MULTILINE)
    return m[-1] if m else ""


def verdict(text):
    m = re.findall(r"^VERDICT: (APPROVED|REJECTED)", text, re.MULTILINE)
    return m[-1] if m else "REJECTED"   # no verdict = not approved


def brief(text, width=150, keep=2):
    """Short version for the live panes: first lines + any RESULT/VERDICT line. Full text stays in the run artifacts."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    shown = lines[:keep] + [ln for ln in lines[keep:] if ln.startswith(("RESULT:", "VERDICT:"))]
    out = [ln if len(ln) <= width else ln[: width - 2] + ".." for ln in shown]
    if len(lines) > len(shown):
        out.append(f"  (+{len(lines) - len(shown)} more lines, full text in the run folder)")
    return chr(10).join(out)


def _short(d):
    if isinstance(d, dict):
        s = next((d[k] for k in ("file_path", "command", "pattern", "path") if k in d), next(iter(d.values()), ""))
    else:
        s = d
    return str(s).replace("\n", " ")[:90]


class Runner:
    def __init__(self, project, cfg, log, sleep=time.sleep, usage=None):
        self.project, self.cfg, self.log, self.sleep = project, cfg, log, sleep
        self.usage = usage or Usage(getattr(log, "dir", None))

    # public API used by the pipeline (tests replace this class with a fake)
    def claude(self, role, agent, prompt, model=None):
        exe = shutil.which("claude") or "claude"
        cmd = [exe, "-p", "--verbose", "--output-format", "stream-json", "--agent", agent, "--permission-mode", "acceptEdits",
               *(["--model", model] if model else []), prompt]
        return self._run(role, cmd, claude=True)

    def agy(self, role, model, prompt):
        exe = shutil.which("agy") or "agy"
        return self._run(role, [exe, "--model", model, "--output-format", "json", "-p", prompt], claude=False, model=model)

    def _run(self, role, cmd, claude, model=None):
        rl, n = self.cfg["rate_limit"], 0
        while True:
            rc, answer, raw = self._once(role, cmd, claude, model)
            if rc == 0:
                return answer
            if AUTH.search(raw):
                raise AuthError(f"{role}: not logged in (run the CLI once and sign in)")
            if is_rate_limited(raw):
                n += 1
                if n > rl["max_waits"]:
                    raise RateLimitExhausted(f"{role}: rate limit did not clear")
                wait = min(rl["cap_seconds"], rl["base_seconds"] * 2 ** (n - 1))
                self.log.say(role, f"!! rate limited, waiting {wait}s (retry {n}/{rl['max_waits']})")
                self.log.event("rate_limit", agent=role, result=f"waiting {wait}s")
                self.sleep(wait)
                continue
            return answer or raw   # unknown failure: pipeline sees no marker/verdict and blocks safely

    def _once(self, role, cmd, claude, model=None):
        p = subprocess.Popen(cmd, cwd=self.project, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
        raw, shown, final = [], [], None
        for line in p.stdout:
            raw.append(line)
            out = line
            if claude:
                self._count(line, role)
                out, final = self._fmt(line, final)
                if out and not self.cfg.get("verbose") and not out.startswith(("> ", "==")):
                    shown.append(out)
                    out = brief(out)
                    self.log.say(role, out)
                    continue
            if out:
                shown.append(out)
                if claude or self.cfg.get("verbose"):
                    self.log.say(role, out)
        rc = p.wait()
        if not claude:                          # agy prints one JSON object: answer text + token usage
            try:
                obj = json.loads("".join(raw))
                self.usage.feed_agy(obj, role, model or "?")
                shown = [obj.get("response", "")]
                self.log.say(role, shown[0] if self.cfg.get("verbose") else brief(shown[0], keep=8))
            except (ValueError, AttributeError):
                if shown and not self.cfg.get("verbose"):
                    self.log.say(role, brief("".join(shown), keep=8))
        return rc, (final if final is not None else "".join(shown)), "".join(raw)

    def _count(self, line, role):
        try:
            self.usage.feed_claude(json.loads(line), role)
        except (ValueError, AttributeError):
            pass

    @staticmethod
    def _fmt(line, final):
        try:
            ev = json.loads(line)
        except ValueError:
            return line, final
        t = ev.get("type")
        if t == "assistant":
            parts = []
            for b in ev.get("message", {}).get("content", []):
                if b.get("type") == "text":
                    parts.append(b["text"])
                elif b.get("type") == "tool_use":
                    parts.append(f"> {b['name']} {_short(b.get('input'))}")
            return "\n".join(parts), final
        if t == "result":
            return f"== finished ({ev.get('duration_ms', 0) // 1000}s)", ev.get("result", "")
        return "", final
