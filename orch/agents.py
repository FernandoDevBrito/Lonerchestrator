"""Runs the agent CLIs (claude, agy) headless, streams their output live, retries on rate limits."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import folder, providers
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
    def __init__(self, project, cfg, log, sleep=time.sleep, usage=None, home=None, board=None):
        """Agents work in `project` (the checkout, or a card's worktree). `home` is the project's folder (folder.py), `board` the board
        of the cards they are given (a card in its own worktree has its own)."""
        self.project, self.cfg, self.log, self.sleep = project, cfg, log, sleep
        self.usage = usage or Usage(getattr(log, "dir", None))
        self.home = Path(home) if home else folder.of(project)
        self.board = Path(board) if board else self.home / "board"

    def at(self, path, board=None):
        """The same runner, working in another folder (a part-worktree of the card, see pipeline._team)."""
        return Runner(path, self.cfg, self.log, sleep=self.sleep, usage=self.usage, home=self.home, board=board or self.board)

    def dirs(self):
        """What an agent may read and change outside the project: its board, context/, memory/ and this run's files (feedback, review
        input). Never the folder's config, agents, rules or CI script: those stay as you set them."""
        out = [self.board, self.home / "context", self.home / "memory"] + ([Path(self.log.dir)] if getattr(self.log, "dir", None) else [])
        for d in out:
            d.mkdir(parents=True, exist_ok=True)
        return [str(d) for d in out]

    def _claude_files(self, agent, model):
        """The agent (--agents), its permissions (--settings) and the rules (--append-system-prompt) from the folder, with `{folder}` and
        `{ci}` filled in. Files go to the folder's claude/, which no agent can reach."""
        h, out = self.home, self.home / "claude"
        out.mkdir(parents=True, exist_ok=True)

        def put(name, text):                     # parallel cards write the same files: never half a file
            tmp = out / f"{name}.{os.getpid()}.{threading.get_ident()}.tmp"
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, out / name)
            return str(out / name)

        def fill(x):
            return folder.render(x, h, self.cfg) if isinstance(x, str) else [fill(v) for v in x] if isinstance(x, list) else \
                {k: fill(v) for k, v in x.items()} if isinstance(x, dict) else x
        args = []
        meta, body = folder.agent(h, agent)
        if body:
            d = {"description": meta.get("description", agent), "prompt": fill(body)}
            if meta.get("tools"):
                d["tools"] = [t.strip() for t in meta["tools"].split(",") if t.strip()]
            if meta.get("model") and not model:  # the model the config gives the role wins
                d["model"] = meta["model"]
            args += ["--agents", put(f"agent-{agent}.json", json.dumps({agent: d})), "--agent", agent]
        if (h / "settings.json").is_file():
            args += ["--settings", put("settings.json", json.dumps(fill(json.loads((h / "settings.json").read_text(encoding="utf-8")))))]
        if (h / "rules.md").is_file():
            args += ["--append-system-prompt", fill((h / "rules.md").read_text(encoding="utf-8"))]
        return args

    # public API used by the pipeline (tests replace this class with a fake)
    def claude(self, role, agent, prompt, model=None, effort=None, via=None):
        """`via`: a provider that is Claude Code talking to another model server (providers.claude_env): its environment, its usage."""
        exe = shutil.which("claude") or "claude"
        cmd = [exe, "-p", "--verbose", "--output-format", "stream-json", "--add-dir", *self.dirs(), *self._claude_files(agent, model),
               "--permission-mode", "acceptEdits", *(["--model", model] if model else []), *(["--effort", effort] if effort else []), prompt]
        return self._run(role, cmd, claude=True, **({"spec": via, "model": model} if via else {}))

    def provider(self, role, pid, model, prompt, mode="read", effort=None):
        """Any AI CLI described in the registry (presets + config `providers`). mode: "edit" may change project files, "read" must not."""
        reg = providers.registry(self.cfg)
        if pid not in reg:
            raise ValueError(f"{role} uses an AI called '{pid}' that is not defined (see `providers` in the project's config.json)")
        spec = reg[pid]
        argv, stdin = providers.build_argv(spec, model, self._fit(prompt, spec, role), mode, effort, dirs=self.dirs())
        return self._run(role, argv, claude=False, model=model, spec=spec, stdin=stdin, ptok=len(prompt) // 4)

    def _fit(self, prompt, spec, role):
        """A very long prompt cannot travel as one command-line argument (Windows allows about 32k characters): park it in a file instead."""
        if spec["prompt_via"] != "arg" or len(prompt) <= 24000:
            return prompt
        f = Path(getattr(self.log, "dir", self.project)) / f"prompt-{role}.txt"
        f.write_text(prompt, encoding="utf-8")
        return f"Your full instructions are in the file {f.as_posix()}. Read it and do exactly what it says."

    def _run(self, role, cmd, claude, model=None, spec=None, stdin=None, ptok=0):
        rl, n = self.cfg["rate_limit"], 0
        while True:
            rc, answer, raw = self._once(role, cmd, claude, model, spec, stdin, ptok)
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

    def _once(self, role, cmd, claude, model=None, spec=None, stdin=None, ptok=0):
        t0 = time.time()
        env = providers.claude_env(spec, model) if claude and spec else None
        p = subprocess.Popen(cmd, cwd=self.project, stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
        limit = self.cfg.get("card_timeout_min", 45) * 60
        watchdog = threading.Timer(limit, p.kill)          # a CLI waiting for an approval or a dead server must not hang the run forever
        watchdog.daemon = True
        watchdog.start()
        if stdin is not None:                      # written from a thread so a big prompt cannot deadlock against our reading of the output
            def feed():
                try:
                    p.stdin.write(stdin)
                    p.stdin.close()
                except OSError:
                    pass
            threading.Thread(target=feed, daemon=True).start()
        raw, shown, final = [], [], None
        for line in p.stdout:
            raw.append(line)
            out = line
            if claude:
                self._count(line, role, spec)
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
        watchdog.cancel()
        if time.time() - t0 >= limit:
            self.log.say(role, f"!! no answer in {limit // 60:g} min (card_timeout_min): stopped")
        if not claude:
            spec = spec or providers.registry(self.cfg)["agy"]
            answer, u = providers.parse_output(spec, "".join(raw))
            if rc == 0:                          # a failed attempt (rate limit, login) used nothing worth counting
                est = u is None
                if est:                          # the CLI reports no tokens: estimate (about 4 characters per token), flagged as an estimate
                    u = {"in": ptok, "out": len(answer) // 4, "secs": 0}
                price = spec.get("price") or {}
                cost = (u["in"] * price.get("in", 0) + u["out"] * price.get("out", 0)) / 1e6
                self.usage.add(spec["id"], model or providers.DEFAULT_MODEL, role, u["in"], u["out"], cost, u["secs"] or time.time() - t0, est=est)
            if answer and not self.cfg.get("verbose"):
                self.log.say(role, brief(answer, keep=8))
            elif answer and spec["output"] != "text":
                self.log.say(role, answer)
            return rc, answer, "".join(raw)
        return rc, (final if final is not None else "".join(shown)), "".join(raw)

    def _count(self, line, role, spec=None):
        try:
            self.usage.feed_claude(json.loads(line), role, spec)
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
