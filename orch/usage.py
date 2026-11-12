"""Real usage numbers, as exposed by the CLIs themselves.

Claude Code reports your account's rate-limit windows (5-hour session, weekly) in its stream, plus tokens per call.
The Antigravity CLI (`agy`) reports tokens per call but does not expose remaining quota.
Account limits are stored once per user (shared by all projects); per-call usage is stored per run."""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

_lock = threading.Lock()
PROBE = {"running": False, "msg": ""}      # state of a manual refresh, shown in the panel


def home():
    return Path(os.environ.get("LONERCHESTRATOR_HOME") or Path.home() / ".lonerchestrator")


def alias(model_key):
    """'claude-sonnet-5-5' -> 'sonnet'."""
    return next((a for a in ("sonnet", "opus", "haiku") if a in model_key), model_key)


def _write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- account limits (Claude)
def set_claude_limits(info):
    """info = the `rate_limit_info` object of a Claude Code stream event."""
    windows = info.get("unifiedWindows")
    if not windows:
        windows = {info.get("rateLimitType", "window"): {"utilization": info.get("utilization"), "resetsAt": info.get("resetsAt"),
                                                         "status": info.get("status")}}
    with _lock:
        f = home() / "limits.json"
        data = _read(f)
        cur = data.get("claude", {}).get("windows", {})
        cur.update(windows)
        data["claude"] = {"updated": time.time(), "status": info.get("status", "?"), "windows": cur}
        _write_atomic(f, data)


def read_limits():
    return _read(home() / "limits.json")


# ---------------------------------------------------------------- per-call usage (per run)
class Usage:
    """Appends one line per CLI call to <run>/usage.jsonl and feeds account limits."""

    def __init__(self, run_dir=None):
        self.run_dir = Path(run_dir) if run_dir else None

    def add(self, ai, model, role, tin, tout, cost=0.0, secs=0.0, est=False):
        if not self.run_dir:
            return
        rec = {"ts": time.time(), "ai": ai, "model": model, "role": role, "in": int(tin or 0), "out": int(tout or 0),
               "cost": float(cost or 0), "secs": round(secs, 1), **({"est": True} if est else {})}
        with _lock, (self.run_dir / "usage.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def feed_claude(self, ev, role, spec=None):
        """One stream-json event from `claude -p`. `spec`: Claude Code was talking to another server (providers.claude_env), so the tokens
        are that AI's, priced with its `price` (Claude Code's own cost uses Anthropic's prices) and its limits are not your Claude account's."""
        t = ev.get("type")
        if t == "rate_limit_event" and ev.get("rate_limit_info") and not spec:
            set_claude_limits(ev["rate_limit_info"])
        elif t == "result":
            secs = ev.get("duration_ms", 0) / 1000
            for key, m in (ev.get("modelUsage") or {}).items():
                tin = m.get("inputTokens", 0) + m.get("cacheReadInputTokens", 0) + m.get("cacheCreationInputTokens", 0)
                tout = m.get("outputTokens", 0)
                if spec:
                    price = spec.get("price") or {}
                    self.add(spec["id"], key, role, tin, tout, (tin * price.get("in", 0) + tout * price.get("out", 0)) / 1e6, secs)
                else:
                    self.add("claude", alias(key), role, tin, tout, m.get("costUSD", 0), secs)

    def feed_agy(self, obj, role, model):
        """The JSON object printed by `agy --output-format json -p`."""
        u = obj.get("usage") or {}
        self.add("agy", model, role, u.get("input_tokens", 0) + u.get("cache_read_tokens", 0), u.get("output_tokens", 0), 0.0,
                 obj.get("duration_seconds", 0))


def _records(files):
    out = []
    for f in files:
        try:
            for ln in Path(f).read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
        except OSError:
            pass
    return out


def totals(records):
    """{ai: {model: {calls, in, out, cost}}}"""
    t = {}
    for r in records:
        m = t.setdefault(r["ai"], {}).setdefault(r["model"], {"calls": 0, "in": 0, "out": 0, "cost": 0.0})
        m["calls"] += 1
        m["in"] += r["in"]
        m["out"] += r["out"]
        m["cost"] += r.get("cost", 0)
        if r.get("est"):
            m["est"] = True                      # at least one call was estimated, not reported by the CLI
    return t


def _runs(project):
    from .folder import of  # late: folder.py builds on home() above
    return of(project) / "runs"


def run_totals(project, run_id):
    return totals(_records([_runs(project) / run_id / "usage.jsonl"] if run_id else []))


def all_totals(project):
    return totals(_records(sorted(_runs(project).glob("*/usage.jsonl"))))


# ---------------------------------------------------------------- rolling windows and budgets (any AI)
PERIODS = {"5h": 5 * 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400}


def all_records(project):
    return _records(sorted(_runs(project).glob("*/usage.jsonl")))


def window_totals(project, now=None, records=None):
    """{ai: {model: {"5h"|"day"|"week"|"month": {calls, in, out, cost, est?}}}}: usage over rolling windows, from every run of this project."""
    now = now or time.time()
    out = {}
    for r in records if records is not None else all_records(project):
        for per, secs in PERIODS.items():
            if now - r["ts"] <= secs:
                w = out.setdefault(r["ai"], {}).setdefault(r["model"], {}).setdefault(per, {"calls": 0, "in": 0, "out": 0, "cost": 0.0})
                w["calls"] += 1
                w["in"] += r["in"]
                w["out"] += r["out"]
                w["cost"] += r.get("cost", 0)
                if r.get("est"):
                    w["est"] = True
    return out


def budget_state(cfg, project, now=None, records=None):
    """The budgets the user set in config (`budgets`), measured over a rolling window. A key is an AI ("agy") or one model ("agy/gemini-x"):

        "budgets": {"agy": {"tokens": 5000000, "per": "day"}, "codex": {"calls": 200, "per": "5h", "cost": 20.0}}

    Returns [{key, per, used, limit, unit, frac, resets_in, est}]: one entry per limit set. `resets_in` is when the oldest call in the window
    stops counting. This is how CLIs that do not publish their quota (Antigravity, Codex, Gemini, local models) still get a limit bar."""
    now = now or time.time()
    recs = records if records is not None else all_records(project)
    out = []
    for key, b in (cfg.get("budgets") or {}).items():
        per = b.get("per", "day")
        if per not in PERIODS:
            continue
        mine = [r for r in recs if now - r["ts"] <= PERIODS[per] and key in (r["ai"], f"{r['ai']}/{r['model']}")]
        used = {"tokens": sum(r["in"] + r["out"] for r in mine), "calls": len(mine), "cost": sum(r.get("cost", 0) for r in mine)}
        for unit in ("tokens", "calls", "cost"):
            if b.get(unit):
                out.append({"key": key, "per": per, "unit": unit, "used": used[unit], "limit": b[unit], "frac": used[unit] / b[unit],
                            "resets_in": (min(r["ts"] for r in mine) + PERIODS[per] - now) if mine else 0, "est": any(r.get("est") for r in mine)})
    return out


# ---------------------------------------------------------------- manual refresh
def probe_claude(project):
    """One tiny haiku call to refresh the account limits. Costs a few thousand tokens, so it only runs when asked."""
    import shutil
    if PROBE["running"]:
        return
    PROBE.update(running=True, msg="asking Claude Code for your current limits...")
    try:
        exe = shutil.which("claude")
        if not exe:
            PROBE["msg"] = "claude CLI not found"
            return
        p = subprocess.run([exe, "-p", "--verbose", "--output-format", "stream-json", "--model", "haiku", "reply with the word ok"],
                           cwd=project, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
                           stdin=subprocess.DEVNULL)
        found = False
        for ln in p.stdout.splitlines():
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if ev.get("type") == "rate_limit_event" and ev.get("rate_limit_info"):
                set_claude_limits(ev["rate_limit_info"])
                found = True
        PROBE["msg"] = "limits updated" if found else "Claude Code did not report limits (log in?)"
    except (OSError, subprocess.TimeoutExpired) as e:
        PROBE["msg"] = f"refresh failed: {type(e).__name__}"
    finally:
        PROBE["running"] = False


def probe_in_background(project):
    threading.Thread(target=probe_claude, args=(project,), daemon=True).start()
