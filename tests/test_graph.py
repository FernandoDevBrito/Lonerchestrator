"""The change graph (graph.py, symbols.py, graphview.py): diff -> symbols -> edges -> model, and every way it is drawn."""
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from orch import graph, graphview, symbols, term
from orch.board import create_card
from orch.cli import main

GOLDEN = Path(__file__).parent / "golden" / "change_graph.json"
GUARD = {"protected": ["scripts/**", ".claude/**"], "max_files": 25, "max_diff_lines": 1000, "scan_secrets": True, "forbid_test_deletion": True}

BASE = {
    "web/notifier.ts": '''import { Booking } from "./booking";

export class Notifier {
  emit(event: string, b: Booking) {
    console.log(event, b.id);
  }
}
''',
    "web/booking.ts": "export interface Booking { id: string }\n",
    "Billing/InvoiceService.cs": '''namespace Acme.Billing
{
    public class InvoiceService
    {
        public int Count { get; set; }

        public void Create(Order order)
        {
            Count += 1;
        }
    }
}
''',
    "app/billing.py": '''"""Billing."""
from .store import Store


class Invoice:
    total: int = 0

    def add(self, amount):
        self.total += amount
        return self


def make_invoice(store: Store):
    inv = Invoice()
    store.keep(inv)
    return inv
''',
    "app/store.py": "class Store:\n    def keep(self, thing):\n        self.last = thing\n",
    "app/report.py": "from .billing import make_invoice\n\n\ndef monthly(store):\n    return make_invoice(store)\n",
    "tests/test_billing.py": "from app.billing import make_invoice\n\n\ndef test_make():\n    assert make_invoice\n",
}
CHANGE = {
    "web/notifier.ts": '''import { Booking } from "./booking";
import { send } from "./http";

export class Notifier {
  emit(event: string, b: Booking) {
    send(event, b.id);
  }
}
''',
    "web/http.ts": 'export function send(event: string, id: string) {\n  return fetch("/hook/" + event + id);\n}\n',
    "Billing/InvoiceService.cs": '''namespace Acme.Billing
{
    public class InvoiceService
    {
        public int Count { get; set; }

        public void Create(Order order)
        {
            Count += 1;
            Audit(order);
        }

        private void Audit(Order order)
        {
        }
    }
}
''',
    "app/billing.py": '''"""Billing."""
from .store import Store
from .tax import vat


class Invoice:
    total: int = 0

    def add(self, amount):
        self.total += vat(amount)
        return self

    def discount(self, pct):
        self.total -= self.total * pct
        return self


def make_invoice(store: Store, pct=0):
    inv = Invoice().discount(pct)
    store.keep(inv)
    return inv
''',
    "app/tax.py": 'def vat(amount):\n    api_key = "sk_live_0123456789abcdef"\n    return amount * 1.2\n',
}


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


def write(root, files):
    for path, text in files.items():
        p = Path(root) / path
        p.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            p.unlink()
        elif isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text, encoding="utf-8", newline="\n")


def card_branch(project, base_files, change, cid="001-thing"):
    """base_files committed on main, `change` committed on card/<cid>."""
    write(project, base_files)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "base", "--allow-empty")
    git(project, "checkout", "-qb", f"card/{cid}")
    write(project, change)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "card")
    git(project, "checkout", "-q", "main")
    return cid


def digest(m):
    lab = graph.label(m)
    return ([(f["path"], f["status"], s["qual"] or "<module>", s["kind"], s["status"], s["added"], s["removed"]) for f in m["files"] for s in f["symbols"]],
            sorted((lab[e["from"]], e["kind"], lab[e["to"]], e["status"]) for e in m["edges"]))


# ---------------------------------------------------------------- symbols

def test_symbols_outline_python_typescript_csharp():
    py, _, _ = symbols.parse("a.py", BASE["app/billing.py"])
    assert [(s["qual"], s["kind"], s["start"], s["end"]) for s in py] == [
        ("Invoice", "class", 5, 10), ("Invoice.total", "field", 6, 6), ("Invoice.add", "method", 8, 10), ("make_invoice", "function", 13, 16)]
    ts, uses, _ = symbols.parse("n.ts", CHANGE["web/notifier.ts"])
    assert [(s["qual"], s["kind"], s["start"], s["end"]) for s in ts] == [("Notifier", "class", 4, 8), ("Notifier.emit", "method", 5, 7)]
    assert (2, "send", "import", "./http:send") in uses
    cs, _, _ = symbols.parse("i.cs", CHANGE["Billing/InvoiceService.cs"])
    assert [(s["qual"], s["start"], s["end"]) for s in cs] == [
        ("InvoiceService", 3, 16), ("InvoiceService.Count", 5, 5), ("InvoiceService.Create", 7, 11), ("InvoiceService.Audit", 13, 15)]


def test_strings_and_comments_never_open_a_scope():
    code = 'class A {\n  // }\n  s = "}{";\n  t = `\n}`;\n  m() { return 1 }\n}\n'
    syms, _, _ = symbols.parse("x.ts", code)
    assert [(s["qual"], s["start"], s["end"]) for s in syms][-1] == ("A.m", 6, 6)
    assert syms[0]["end"] == 7


def test_a_file_that_does_not_parse_still_gets_an_outline():
    syms, uses, note = symbols.parse("bad.py", "def ok():\n    return 1\n\ndef broken(:\n    pass\n")
    assert [s["qual"] for s in syms] == ["ok", "broken"] and uses == [] and "syntax error" in note


# ---------------------------------------------------------------- the model

def test_three_language_diff_matches_the_golden_model(project):
    card_branch(project, BASE, CHANGE)
    m = graph.build(project, "main", "card/001-thing", card="001-thing", guard=GUARD)
    m.pop("snapshot")
    if os.environ.get("UPDATE_GOLDEN"):                       # after an intended change: UPDATE_GOLDEN=1 pytest tests/test_graph.py
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    assert m == json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows, edges = digest(m)
    assert ("app/tax.py", "added", "vat", "function", "added", 3, 0) in rows
    assert ("app/billing.py", "modified", "Invoice.discount", "method", "added", 2, 0) in rows
    assert ("app/report.py:4 monthly", "calls", "app/billing.py:18 make_invoice", "kept") in edges             # a caller in an unchanged file
    assert ("tests/test_billing.py:4 test_make", "tests", "app/billing.py:18 make_invoice", "kept") in edges   # a test of a changed symbol
    assert ("web/notifier.ts:5 Notifier.emit", "calls", "web/http.ts:1 send", "added") in edges
    assert ("Billing/InvoiceService.cs:7 InvoiceService.Create", "calls", "Billing/InvoiceService.cs:13 InvoiceService.Audit", "added") in edges
    assert [s["qual"] for f in m["files"] for s in f["symbols"] if s.get("hotspot")] == ["make_invoice"]


def test_the_same_change_gives_the_same_bytes(project):
    card_branch(project, BASE, CHANGE)

    def once():
        m = graph.build(project, "main", "card/001-thing", card="001-thing", guard=GUARD)
        m["snapshot"].pop("createdAt")
        return graph.dumps(m)
    assert once() == once()


def test_secrets_are_redacted_and_pinned_to_their_symbol(project):
    card_branch(project, BASE, CHANGE)
    m = graph.build(project, "main", "card/001-thing", card="001-thing", guard=GUARD)
    assert "sk_live" not in graph.dumps(m)
    vat = next(s for f in m["files"] for s in f["symbols"] if s["qual"] == "vat")
    assert vat["guardrails"] == ["possible secret in added line 2"]
    assert graph.REDACTED in "".join(ln for o, n, ln in graph.lines_of(m, vat["id"]))


def test_protected_files_show_no_content(project):
    card_branch(project, {"scripts/ci.sh": "echo ok\n"}, {"scripts/ci.sh": "echo hacked\nexit 0\n"})
    m = graph.build(project, "main", "card/001-thing", guard=GUARD)
    f = m["files"][0]
    assert f["path"] == "scripts/ci.sh" and f["hunks"] == [] and "protected" in f["note"] and f["guardrails"] == ["protected path modified"]
    assert "hacked" not in graph.dumps(m)


def test_unreadable_files_become_one_row_and_never_break_the_graph(project):
    change = {"img.png": b"\x89PNG\r\n\x1a\n\x00\x00binary", "big.py": "x = 1\n" * 200_000, "lib.min.js": "var a=1;" * 300,
              "gen.ts": "// @generated by a tool\nexport const a = 1;\n", "broken.py": "def f(:\n    pass\n", "notes.xyz": "plain text\n"}
    card_branch(project, {}, change)
    m = graph.build(project, "main", "card/001-thing", guard=GUARD)
    notes = {f["path"]: f["note"] for f in m["files"]}
    assert notes["img.png"].startswith("binary") and notes["big.py"].startswith("bigger than 1 MB") and notes["lib.min.js"].startswith("generated")
    assert notes["gen.ts"].startswith("generated") and "syntax error" in notes["broken.py"] and "no outline" in notes["notes.xyz"]
    assert all(f["symbols"] for f in m["files"])                                  # every file still shows, at least as one row


def test_moving_code_adds_no_edge(project):
    before = "def a():\n    return b()\n\n\ndef b():\n    return 1\n\n\ndef c():\n    return a()\n"
    after = "def c():\n    return a()\n\n\ndef b():\n    return 1\n\n\ndef a():\n    return b()\n"
    card_branch(project, {"m.py": before}, {"m.py": after})
    m = graph.build(project, "main", "card/001-thing", guard=GUARD)
    assert m["edges"] and all(e["status"] == "kept" for e in m["edges"])
    assert all(s.get("moved") for f in m["files"] for s in f["symbols"] if s["status"] == "modified")


def test_a_renamed_function_is_one_symbol_not_two(project):
    body = "    total = 0\n    for x in items:\n        total += x\n    total = round(total, 2)\n    return total\n"
    card_branch(project, {"m.py": f"def sum_all(items):\n{body}"}, {"m.py": f"def add_up(items):\n{body}"})
    m = graph.build(project, "main", "card/001-thing", guard=GUARD)
    (s,) = [s for f in m["files"] for s in f["symbols"] if s["kind"] == "function"]
    assert s["qual"] == "add_up" and s["status"] == "modified" and s["from"] == {"path": "m.py", "qual": "sum_all"}


def test_staged_changes_are_what_the_pipeline_graphs(project):
    write(project, {"m.py": "def a():\n    return 1\n"})
    git(project, "add", "-A")
    git(project, "commit", "-qm", "base")
    write(project, {"m.py": "def a():\n    return 2\n\n\ndef b():\n    return a()\n"})
    git(project, "add", "-A")
    m = graph.build(project, "main", staged=True, card="001-thing", attempt=1, guard=GUARD)
    assert m["snapshot"]["source"] == "staged" and m["snapshot"]["attempt"] == 1
    assert digest(m)[1] == [("m.py:5 b", "calls", "m.py:1 a", "added")]


# ---------------------------------------------------------------- reading: snapshots, findings, filters, attempts

def save(project, cid, n, model, reviews=None, run="20261111-101500"):
    d = Path(project) / ".orchestrator" / "runs" / run / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / f"graph{n}.json").write_text(graph.dumps(model), encoding="utf-8")
    for who, text in (reviews or {}).items():
        (d / f"review{n}-{who}.txt").write_text(text, encoding="utf-8")


def test_reviewer_failures_land_on_the_symbol_they_name(project):
    card_branch(project, BASE, CHANGE)
    m = graph.build(project, "main", "card/001-thing", card="001-thing", attempt=1, guard=GUARD)
    review = "CRITERIA\n- [not met] x: y\nFAILURES\n- app/billing.py:19 make_invoice ignores a negative pct\n- something vague\nVERDICT: REJECTED\n"
    save(project, "001-thing", 1, m, {"qa": review})
    got, snaps = graph.load(project, "001-thing", "main")
    assert [s["key"] for s in snaps] == ["20261111-101500/1"]
    mk = next(s for f in got["files"] for s in f["symbols"] if s["qual"] == "make_invoice")
    assert mk["findings"] == [{"reviewer": "qa", "severity": "blocking", "text": "app/billing.py:19 make_invoice ignores a negative pct", "line": 19}]
    assert got["findings"][0]["text"] == "something vague" and got["stats"]["findings"] == 2
    assert graph.failures("FAILURES\n- none\nVERDICT: APPROVED") == []


def test_snapshot_keys_cannot_leave_the_runs_folder(project):
    assert graph.read(project, "../x", "20261111-101500/1") is None
    assert graph.read(project, "001", "../../etc/1") is None
    assert graph.snapshots(project, "*") == []


def test_filters_keep_parents_and_focus_follows_edges(project):
    card_branch(project, BASE, CHANGE)
    m = graph.build(project, "main", "card/001-thing", guard=GUARD)
    added = graph.view(m, only=("added",))
    assert {s["status"] for f in added["files"] for s in f["symbols"]} == {"added", "modified"}       # Invoice stays as the parent of discount
    near = graph.view(m, focus="make_invoice")
    assert {s["qual"] for f in near["files"] for s in f["symbols"]} >= {"make_invoice", "monthly", "test_make", "Invoice.discount"}
    assert "vat" not in {s["qual"] for f in near["files"] for s in f["symbols"]}
    assert graph.view(m, hide=("tests",))["stats"]["symbols"] < m["stats"]["symbols"]


def test_compare_shows_what_the_fix_loop_changed(project):
    card_branch(project, BASE, CHANGE)
    two = graph.build(project, "main", "card/001-thing", guard=GUARD)
    git(project, "checkout", "-q", "card/001-thing")
    write(project, {"app/tax.py": None})
    write(project, {"app/billing.py": CHANGE["app/billing.py"].replace("from .tax import vat\n", "").replace("vat(amount)", "amount")})
    git(project, "add", "-A")
    git(project, "commit", "-qm", "fix")
    git(project, "checkout", "-q", "main")
    three = graph.build(project, "main", "card/001-thing", guard=GUARD)
    c = graph.compare(two, three)
    delta = {s["qual"]: s["delta"] for f in c["files"] for s in f["symbols"]}
    assert delta["vat"] == "gone" and delta["Invoice.add"] == "gone" and delta["Invoice"] == "changed" and delta["make_invoice"] == "same"
    assert any(e["delta"] == "gone" and e["kind"] == "calls" for e in c["edges"])


# ---------------------------------------------------------------- drawing

def test_layout_is_stable_and_collapsing_moves_nothing_sideways(project):
    card_branch(project, BASE, CHANGE)
    m = graph.build(project, "main", "card/001-thing", guard=GUARD)
    a, b = graphview.layout(m), graphview.layout(m)
    assert a == b and a["edges"] and all(e["d"].startswith("M") for e in a["edges"])
    fid = next(f["id"] for f in m["files"] if f["path"] == "app/billing.py")
    c = graphview.layout(m, collapsed=[fid])
    assert c["files"][fid]["h"] == graphview.HEAD and {k: v["x"] for k, v in c["files"].items()} == {k: v["x"] for k, v in a["files"].items()}
    caller = next(f["id"] for f in m["files"] if f["path"] == "app/report.py")
    assert a["files"][caller]["x"] < a["files"][fid]["x"]                       # whoever uses sits left of what it uses


def test_exports_are_plain_text_formats(project):
    card_branch(project, BASE, CHANGE)
    m = graph.build(project, "main", "card/001-thing", guard=GUARD)
    svg = graphview.svg(m)
    assert svg.startswith("<svg") and "<script" not in svg and "http://www.w3.org/2000/svg" in svg and "gradient" not in svg
    assert graphview.mermaid(m).startswith("flowchart LR") and graphview.dot(m).startswith("digraph change {")


def test_nothing_from_the_model_reaches_a_terminal_as_an_escape_sequence():
    m = {"snapshot": {}, "stats": {"files": 1, "symbols": 1, "changes": 1, "added": 1, "removed": 0, "hotspots": 0, "findings": 0, "edges": 0},
         "files": [{"id": "f", "path": "evil\x1b]0;pwned\x07.py", "oldPath": None, "status": "added", "added": 1, "removed": 0, "note": "",
                    "guardrails": [], "hunks": [], "symbols": [{"id": "s", "name": "x\x1b[2J", "qual": "x", "kind": "function", "parent": None,
                                                              "status": "added", "added": 1, "removed": 0, "churnBucket": 1, "range": {"start": 1, "end": 1},
                                                              "findings": [], "guardrails": []}]}],
         "edges": [], "groups": [{"id": "g", "label": ".", "fileIds": ["f"]}], "guardrails": [], "findings": []}
    for text in (graphview.tree(m), graphview.mermaid(m), graphview.dot(m), graphview.svg(m), graphview.frame(m, {"cur": 0, "open": {"s"}, "fold": set()}, 80, 20, color=False)):
        assert "\x1b" not in text and "\x07" not in text


def test_the_interactive_view_draws_the_cursor_and_an_opened_diff(project):
    card_branch(project, BASE, CHANGE)
    m = graph.build(project, "main", "card/001-thing", guard=GUARD)
    rows = graphview.visible(m, {"fold": set()})
    i = next(i for i, r in enumerate(rows) if r[2] and r[2]["qual"] == "Invoice.discount")
    screen = graphview.frame(m, {"cur": i, "open": {rows[i][2]["id"]}, "fold": set()}, 100, 40, color=False)
    lines = screen.splitlines()
    assert lines[0].startswith("Graph:") and "discount" in "\n".join(lines) and "+    def discount(self, pct):" in screen
    assert lines[-1] == graphview.HELP


# ---------------------------------------------------------------- the command

def test_graph_command_prints_a_plain_tree_in_a_pipe(project, capsys, monkeypatch):
    cid = create_card(project, "Billing discounts").stem
    card_branch(project, BASE, CHANGE, cid=cid)
    assert main(["-C", str(project), "graph", cid[:3]]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and out.startswith("Graph: ") and "make_invoice" in out and "<- used by monthly (app/report.py)" in out
    assert all(len(ln) <= 80 for ln in out.splitlines())
    assert main(["-C", str(project), "graph", cid, "--format", "json", "--only", "added"]) == 0
    m = json.loads(capsys.readouterr().out)
    assert m["schemaVersion"] == 1 and {s["status"] for f in m["files"] for s in f["symbols"]} <= {"added", "modified"}
    assert main(["-C", str(project), "graph", cid, "--format", "ascii", "--focus", "make_invoice", "--ascii"]) == 0
    assert "calls" in capsys.readouterr().out
    out_file = Path(project) / "g.svg"
    assert main(["-C", str(project), "graph", cid, "--format", "svg", "--out", str(out_file)]) == 0
    assert out_file.read_text(encoding="utf-8").startswith("<svg")
    assert main(["-C", str(project), "graph", "999"]) == 1
    assert main(["-C", str(project), "graph", cid, "--attempt", "4"]) == 1
    view, _ = graph.view, capsys.readouterr()
    monkeypatch.setattr(graph, "view", lambda m, **k: {**view(m, **k), "note": "‮[2J"})
    assert main(["-C", str(project), "graph", cid, "--format", "json"]) == 0
    out = capsys.readouterr().out
    assert out.isascii() and json.loads(out)["note"] == "‮[2J"           # printed JSON escapes what a terminal could obey
    monkeypatch.setattr(sys, "stdin", type("Nul", (io.StringIO,), {"isatty": lambda self: True})())    # Windows: stdin from NUL "is a tty"
    monkeypatch.setattr(term, "read_keys", lambda: ["q"])                  # were the check wrong, the loop would quit instead of hang
    assert main(["-C", str(project), "graph", cid, "--tui"]) == 1 and "needs a terminal" in capsys.readouterr().out


def test_a_big_change_is_graphed_in_seconds(project):
    """Synthetic load: 300 files of 100 lines each, all changed, under 10 s (the spec asks 500 files / 50k lines; CI runners are slow)."""
    base = {f"pkg/m{i}.py": "".join(f"def f{j}(x):\n    return g{j}(x)\n\n\n" for j in range(25)) for i in range(300)}
    change = {p: t.replace("return g", "return h") for p, t in base.items()}
    card_branch(project, base, change)
    t = time.time()
    m = graph.build(project, "main", "card/001-thing", guard={**GUARD, "max_files": 10_000, "max_diff_lines": 100_000})
    assert m["stats"]["files"] == 300 and m["stats"]["changes"] == 300 * 25
    assert time.time() - t < 10, f"took {time.time() - t:.1f}s"
    assert not re.search(r"\d+ files changed", " ".join(m["guardrails"]))


# ---- the pipeline hook ----------------------------------------------------------------------------------------
def test_every_attempt_saves_its_graph_and_each_reviewers_words(project, cfg, log):
    from conftest import add_card
    from test_pipeline import Fake, names

    from orch.pipeline import Pipeline
    add_card(project)
    verdicts = iter(["FAILURES\n- thing.py:2 returns a constant\nVERDICT: REJECTED", "FAILURES\n- none\nVERDICT: APPROVED"])
    fake = Fake(project)
    fake.agy = lambda role, model, prompt: next(verdicts)
    assert Pipeline(project, cfg, log, fake).run() == 0
    assert names(project, "done") == ["001-thing.md"]                            # a view only: the card's way through is unchanged
    d = log.dir / "001-thing"
    assert sorted(p.name for p in d.glob("graph*.json")) == ["graph1.json", "graph2.json"]
    assert (d / "review1-qa.txt").read_text(encoding="utf-8") == "VERDICT: APPROVED" and "REJECTED" in (d / "review1-cross.txt").read_text(encoding="utf-8")
    assert "# CHANGE GRAPH" not in (d / "review1.txt").read_text(encoding="utf-8")   # the reviewers' summary is opt-in
    assert "attempt 1: Graph: 1 file, 1 symbol, 1 change" in (project / "board" / "done" / "001-thing.md").read_text(encoding="utf-8")
    assert '"graph"' in (log.dir / "events.jsonl").read_text(encoding="utf-8")
    first, snaps = graph.load(project, "001-thing", "main", key=f"{log.dir.name}/1")
    assert len(snaps) == 2 and first["stats"]["findings"] == 1
    assert next(s for f in first["files"] for s in f["symbols"] if s["qual"] == "thing")["findings"][0]["severity"] == "blocking"


def test_a_broken_graph_never_stops_a_card_and_the_summary_is_opt_in(project, cfg, log, monkeypatch):
    from conftest import add_card
    from test_pipeline import Fake, names

    from orch.pipeline import Pipeline
    add_card(project)
    cfg["graph"] = {"enabled": True, "review_summary": True}
    monkeypatch.setattr(graph, "build", lambda *a, **k: 1 / 0)
    assert Pipeline(project, cfg, log, Fake(project)).run() == 0
    assert names(project, "done") == ["001-thing.md"] and not list((log.dir / "001-thing").glob("graph*.json"))
    assert "# CHANGE GRAPH" not in (log.dir / "001-thing" / "review1.txt").read_text(encoding="utf-8")


def test_reviewers_can_read_a_summary_computed_from_the_diff(project, cfg, log):
    from conftest import add_card
    from test_pipeline import Fake

    from orch.pipeline import Pipeline
    add_card(project)
    cfg["graph"] = {"enabled": True, "review_summary": True}
    assert Pipeline(project, cfg, log, Fake(project)).run() == 0
    text = (log.dir / "001-thing" / "review1.txt").read_text(encoding="utf-8")
    assert "# CHANGE GRAPH (computed from the diff above)\nGraph: 1 file, 1 symbol, 1 change" in text


def test_the_secret_guardrail_says_where_and_never_what():
    from orch import guardrails
    g = {"protected": [], "max_files": 25, "max_diff_lines": 1000, "scan_secrets": True, "forbid_test_deletion": True}
    diff = ("diff --git a/app/cfg.py b/app/cfg.py\n--- a/app/cfg.py\n+++ b/app/cfg.py\n@@ -1,2 +1,4 @@\n x = 1\n"
            '+api_key = "abcdefghijklmnop"\n y = 2\n+++token = "qrstuvwxyz012345"\n')
    assert guardrails.check_diff(g, ["app/cfg.py"], [], diff) == ["possible secret in added line: app/cfg.py:2",
                                                                    "possible secret in added line: app/cfg.py:4"]   # a line that starts with "++" too


# ---- the web page's view --------------------------------------------------------------------------------------
def test_the_web_view_is_filtered_laid_out_and_never_carries_a_secret(project, monkeypatch):
    import pytest
    from test_web import FakeRunner

    from orch import web, web_graph, webcore
    cid = create_card(project, "Billing discounts").stem
    card_branch(project, BASE, CHANGE, cid=cid)
    app = web.App(project, "main", FakeRunner())

    def get(**q):
        return app.dispatch("GET", f"/api/graph/{cid}", {}, {k: str(v) for k, v in q.items()})
    d = get()
    assert d["key"] == "" and d["snapshots"] == [] and d["model"]["snapshot"]["source"] == "branch" and not d["too_big"]
    assert all(f["hunks"] == [] for f in d["model"]["files"])                     # the page asks for one symbol's lines at a time
    assert set(d["layout"]["files"]) == {f["id"] for f in d["model"]["files"]}
    syms = {s["qual"]: s for f in d["model"]["files"] for s in f["symbols"]}
    assert any(t.startswith("+") and "discount" in t for _, _, t in get(format="lines", sym=syms["make_invoice"]["id"])["lines"])
    out = json.dumps([d, get(format="lines", sym=syms["vat"]["id"]), get(format="svg"), get(format="json"), get(format="mermaid"), get(format="dot")])
    assert "sk_live" not in out and "redacted" in out                             # the guardrails' redaction holds on every way out
    added = {s["qual"] for f in get(only="added")["model"]["files"] for s in f["symbols"]}
    assert "Invoice.discount" in added and "make_invoice" not in added
    assert get(format="svg")["text"].startswith("<svg") and get(format="dot")["name"] == f"{cid}-graph.dot"
    assert get(focus="make_invoice", depth="99")["model"]["stats"]["symbols"] < d["model"]["stats"]["symbols"]   # depth is clamped, not an error
    fid = next(f["id"] for f in d["model"]["files"] if f["path"] == "app/billing.py")
    folded = get(fold=fid + ",../x")["layout"]["files"]
    assert folded[fid]["collapsed"] and all(folded[k]["x"] == v["x"] for k, v in d["layout"]["files"].items())
    for bad in ({"snap": "../../x"}, {"compare": "a..b"}, {"format": "lines", "sym": "../x"}):
        with pytest.raises(webcore.Bad):
            get(**bad)
    with pytest.raises(webcore.Bad):
        app.dispatch("GET", "/api/graph/..%2Fconfig", {}, {})
    assert app.dispatch("GET", "/api/graph/" + create_card(project, "Not started").stem, {}, {})["model"] is None
    monkeypatch.setattr(web_graph, "MAX_DRAW", 3)
    big = get()
    assert big["too_big"] and big["layout"] is None and big["model"]["files"]     # too many to draw: the page lists them instead
