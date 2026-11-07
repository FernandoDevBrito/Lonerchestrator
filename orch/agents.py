"""Runs the agent CLIs (claude, agy) headless, streams their output live, retries on rate limits."""
import json
import re
import shutil
import subprocess
import time

RATE = re.compile(r"rate.?limit|quota|usage limit|too many requests|\b429\b|resource.?exhausted|overloaded|limit reached", re.IGNORECASE)
AUTH = re.compile(r"oauth|failed to authenticate|not logged in|please (run )?/?login|invalid api key", re.IGNORECASE)


class AuthError(Exception):
    pass


class RateLimitExhausted(Exception):
    pass


def marker(text):
    m = re.findall(r"^RESULT: (PLANNED|DONE|BLOCKED)", text, re.MULTILINE)
    return m[-1] if m else ""


def verdict(text):
    m = re.findall(r"^VERDICT: (APPROVED|REJECTED)", text, re.MULTILINE)
    return m[-1] if m else "REJECTED"   # no verdict = not approved


def _short(d):
    if isinstance(d, dict):
        s = next((d[k] for k in ("file_path", "command", "pattern", "path") if k in d), next(iter(d.values()), ""))
    else:
        s = d
    return str(s).replace("\n", " ")[:90]


class Runner:
    def __init__(self, project, cfg, log, sleep=time.sleep):
        self.project, self.cfg, self.log, self.sleep = project, cfg, log, sleep

    # public API used by the pipeline (tests replace this class with a fake)
    def claude(self, role, agent, prompt):
        exe = shutil.which("claude") or "claude"
        cmd = [exe, "-p", "--verbose", "--output-format", "stream-json", "--agent", agent, "--permission-mode", "acceptEdits", prompt]
        return self._run(role, cmd, claude=True)

    def agy(self, role, model, prompt):
        exe = shutil.which("agy") or "agy"
        return self._run(role, [exe, "--model", model, "-p", prompt], claude=False)

    def _run(self, role, cmd, claude):
        rl, n = self.cfg["rate_limit"], 0
        while True:
            rc, answer, raw = self._once(role, cmd, claude)
            if rc == 0:
                return answer
            if AUTH.search(raw):
                raise AuthError(f"{role}: not logged in (run the CLI once and sign in)")
            if RATE.search(raw):
                n += 1
                if n > rl["max_waits"]:
                    raise RateLimitExhausted(f"{role}: rate limit did not clear")
                wait = min(rl["cap_seconds"], rl["base_seconds"] * 2 ** (n - 1))
                self.log.say(role, f"!! rate limited, waiting {wait}s (retry {n}/{rl['max_waits']})")
                self.log.event("rate_limit", agent=role, result=f"waiting {wait}s")
                self.sleep(wait)
                continue
            return answer or raw   # unknown failure: pipeline sees no marker/verdict and blocks safely

    def _once(self, role, cmd, claude):
        p = subprocess.Popen(cmd, cwd=self.project, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
        raw, shown, final = [], [], None
        for line in p.stdout:
            raw.append(line)
            out = line
            if claude:
                out, final = self._fmt(line, final)
            if out:
                shown.append(out)
                self.log.say(role, out)
        rc = p.wait()
        return rc, (final if final is not None else "".join(shown)), "".join(raw)

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
