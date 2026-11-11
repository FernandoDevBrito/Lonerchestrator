import json
import sys

from orch import agents, folder, usage

RESULT = {"type": "result", "duration_ms": 3241, "total_cost_usd": 0.17,
          "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 2, "outputTokens": 4, "cacheReadInputTokens": 100, "cacheCreationInputTokens": 43985,
                                               "costUSD": 0.175984}}}
LIMIT = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "resetsAt": 1794024600, "rateLimitType": "five_hour", "unifiedWindows": {
    "five_hour": {"utilization": 0.48, "resetsAt": 1794024600, "status": "allowed"},
    "seven_day": {"utilization": 0.18, "resetsAt": 1794276000, "status": "allowed"}}}}


def test_claude_events_become_usage_and_limits(tmp_path):
    u = usage.Usage(tmp_path)
    u.feed_claude(LIMIT, "builder")
    u.feed_claude(RESULT, "builder")
    rec = json.loads((tmp_path / "usage.jsonl").read_text().splitlines()[0])
    assert (rec["ai"], rec["model"], rec["role"]) == ("claude", "sonnet", "builder")
    assert rec["in"] == 2 + 100 + 43985 and rec["out"] == 4 and rec["secs"] == 3.2
    lim = usage.read_limits()["claude"]
    assert lim["windows"]["five_hour"]["utilization"] == 0.48 and lim["windows"]["seven_day"]["utilization"] == 0.18


def test_single_window_events_accumulate():
    usage.set_claude_limits({"status": "allowed", "rateLimitType": "five_hour", "resetsAt": 5, "utilization": 0.3})
    usage.set_claude_limits({"status": "allowed", "rateLimitType": "seven_day", "resetsAt": 9, "utilization": 0.1})
    w = usage.read_limits()["claude"]["windows"]
    assert w["five_hour"]["utilization"] == 0.3 and w["seven_day"]["utilization"] == 0.1      # windows merge, not overwrite


def test_agy_usage(tmp_path):
    u = usage.Usage(tmp_path)
    u.feed_agy({"usage": {"input_tokens": 18037, "output_tokens": 1, "cache_read_tokens": 3}, "duration_seconds": 10.9}, "cross", "gemini-x")
    assert usage.totals(usage._records([tmp_path / "usage.jsonl"])) == {"agy": {"gemini-x": {"calls": 1, "in": 18040, "out": 1, "cost": 0.0}}}


def test_totals_per_run_and_all(tmp_path):
    for run, n in (("r1", 1), ("r2", 2)):
        d = folder.of(tmp_path) / "runs" / run
        d.mkdir(parents=True)
        u = usage.Usage(d)
        for _ in range(n):
            u.add("claude", "opus", "qa", 10, 5)
    assert usage.run_totals(tmp_path, "r2")["claude"]["opus"]["calls"] == 2
    assert usage.all_totals(tmp_path)["claude"]["opus"] == {"calls": 3, "in": 30, "out": 15, "cost": 0.0}
    assert usage.run_totals(tmp_path, None) == {}


def test_allowed_rate_limit_event_is_not_a_rate_limit():
    ev = json.dumps(LIMIT)
    assert agents.is_rate_limited(ev + "\nsome unrelated crash") is False        # the event is emitted on every call
    rejected = json.loads(ev)
    rejected["rate_limit_info"]["status"] = "rejected"
    assert agents.is_rate_limited(json.dumps(rejected)) is True
    assert agents.is_rate_limited("Claude AI usage limit reached|1794024600") is True


def test_runner_records_usage_from_a_claude_stream(project, cfg, log):
    events = [LIMIT, {**RESULT, "result": "RESULT: DONE"}]
    script = "import json; [print(json.dumps(e)) for e in " + repr(events) + "]"
    r = agents.Runner(project, cfg, log)
    assert r._run("builder", [sys.executable, "-c", script], claude=True) == "RESULT: DONE"
    assert usage.run_totals(project, log.run_id)["claude"]["sonnet"]["calls"] == 1
    assert usage.read_limits()["claude"]["windows"]["five_hour"]["utilization"] == 0.48


def test_runner_reads_agy_json_answer_and_tokens(project, cfg, log):
    obj = {"status": "SUCCESS", "response": "all good\nVERDICT: APPROVED\n", "duration_seconds": 1.0, "usage": {"input_tokens": 50, "output_tokens": 7}}
    r = agents.Runner(project, cfg, log)
    out = r._run("cross", [sys.executable, "-c", "import json; print(json.dumps(" + repr(obj) + "))"], claude=False, model="gemini-x")
    assert agents.verdict(out) == "APPROVED"
    assert usage.run_totals(project, log.run_id)["agy"]["gemini-x"] == {"calls": 1, "in": 50, "out": 7, "cost": 0.0}
