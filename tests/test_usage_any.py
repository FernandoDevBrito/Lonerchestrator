"""Usage for ANY AI: tokens read from whatever the CLI prints (configurable), an estimate when it prints none, rolling windows, user budgets."""
import json
import time

from conftest import add_card, home
from test_anyai import mine, records  # noqa: F401  (a fake third-party AI in every role)
from test_web import server  # noqa: F401  (the local web server fixture)

from orch import config, providers, usage
from orch.agents import Runner
from orch.pipeline import Pipeline


def spec(**kw):
    return providers._normalize("x", {"cmd": ["x"], **kw})


def test_tokens_are_read_the_way_the_provider_says():
    js = spec(usage={"json": {"in": "usage.prompt", "out": "usage.stats.0.completion"}}, output="text")
    assert providers.extract_usage(js, json.dumps({"usage": {"prompt": 120, "stats": [{"completion": 30}]}})) == {"in": 120, "out": 30, "secs": 0}
    rx = spec(usage={"in_regex": r"input: (\d+)", "out_regex": r"output: ([\d,]+)"})
    assert providers.extract_usage(rx, "done\ninput: 12\noutput: 1,300") == {"in": 12, "out": 1300, "secs": 0}
    tot = spec(usage={"total_regex": r"tokens used\D+([\d,]+)"})
    assert providers.extract_usage(tot, "answer\ntokens used: 4,321") == {"in": 0, "out": 4321, "secs": 0}
    assert providers.extract_usage(spec(), "nothing here") is None and providers.extract_usage(rx, "no numbers") is None
    assert providers.extract_usage(js, "not json") is None


def test_the_ollama_preset_reads_its_statistics_and_keeps_them_out_of_the_answer():
    o = providers.registry({})["ollama"]
    raw = "The answer.\n\ntotal duration:       2.1s\nprompt eval count:    26 token(s)\neval count:           298 token(s)\n"
    answer, u = providers.parse_output(o, raw)
    assert answer == "The answer." and u == {"in": 26, "out": 298, "secs": 0}
    assert providers.registry({})["codex"]["usage"]["total_regex"]


def test_a_cli_that_reports_nothing_gets_an_estimate_flagged_as_such(project, mine, log):  # noqa: F811
    cfg, _ = mine
    cfg["providers"]["mine"]["price"] = {"in": 2.0, "out": 10.0}
    add_card(project)
    assert Pipeline(project, cfg, log, Runner(project, cfg, log)).run() == 0
    t = usage.all_totals(project)["mine"]["big"]
    assert t["calls"] >= 5 and t["est"] is True and t["in"] > 0 and t["cost"] > 0            # estimated tokens, priced by the provider's `price`


def test_rolling_windows_and_budgets(project):
    now = time.time()
    run = home(project) / "runs" / "r1"
    run.mkdir(parents=True)
    rows = [{"ts": now - 600, "ai": "agy", "model": "g", "role": "qa", "in": 600, "out": 400, "cost": 0.0},
            {"ts": now - 6 * 3600, "ai": "agy", "model": "g", "role": "qa", "in": 100, "out": 0, "cost": 0.0, "est": True},
            {"ts": now - 3 * 86400, "ai": "agy", "model": "g", "role": "qa", "in": 5000, "out": 0, "cost": 0.0},
            {"ts": now - 60, "ai": "codex", "model": "default", "role": "builder", "in": 10, "out": 5, "cost": 0.5}]
    (run / "usage.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    w = usage.window_totals(project, now)["agy"]["g"]
    assert (w["5h"]["calls"], w["day"]["calls"], w["week"]["calls"]) == (1, 2, 3) and w["day"]["est"] is True and "est" not in w["5h"]
    cfg = {"budgets": {"agy": {"tokens": 2000, "per": "day"}, "codex/default": {"calls": 2, "cost": 1.0, "per": "5h"}, "bad": {"tokens": 1, "per": "never"}}}
    st = {(b["key"], b["unit"]): b for b in usage.budget_state(cfg, project, now)}
    assert st[("agy", "tokens")]["used"] == 1100 and round(st[("agy", "tokens")]["frac"], 2) == 0.55 and st[("agy", "tokens")]["est"] is True
    assert 0 < st[("agy", "tokens")]["resets_in"] <= 86400 - 6 * 3600 + 1                      # rolling: the 6h-old call leaves first
    assert st[("codex/default", "calls")]["used"] == 1 and st[("codex/default", "cost")]["used"] == 0.5 and len(st) == 3   # the bad period is ignored


def test_budget_api_sets_changes_and_removes(server, project):  # noqa: F811
    call, *_ = server

    def post(**b):
        s, body = call("POST", "/api/budget", b)
        return s, json.loads(body)
    assert post(key="agy", unit="tokens", limit=1000000, per="day")[0] == 200
    assert post(key="agy", unit="calls", limit=50, per="day")[0] == 200
    assert config.read_raw(project)["budgets"]["agy"] == {"per": "day", "tokens": 1000000, "calls": 50}
    ais = json.loads(call("GET", "/api/ais")[1])
    assert {b["unit"] for b in ais["budgets"]} == {"tokens", "calls"} and "agy" in ais["known"] and "windows" in ais
    assert post(key="agy", unit="tokens", limit=0, per="day")[0] == 200 and post(key="agy", unit="calls", limit=0, per="day")[0] == 200
    assert config.read_raw(project).get("budgets", {}) == {}
    for bad in ({"key": "evil", "unit": "tokens", "limit": 5}, {"key": "agy", "unit": "bananas", "limit": 5}, {"key": "agy", "unit": "tokens", "limit": -1},
                {"key": "agy", "unit": "tokens", "limit": "x"}, {"key": "agy", "unit": "tokens", "limit": 5, "per": "year"}):
        assert post(**bad)[0] == 400
