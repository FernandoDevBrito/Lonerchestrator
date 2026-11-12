"""The Map tab (mindmap.py, web_map.py): a change as a mind map, the text each changed symbol carries, and Explain."""
import json

import pytest
from test_graph import BASE, CHANGE, card_branch, git, write
from test_web import FakeRunner

from orch import mindmap, symbols, web, webcore
from orch.board import create_card


def test_a_declaration_says_what_it_does_in_its_docstring_or_the_comment_above():
    py = '"""The module."""\n\n# Helps.\ndef a():\n    pass\n\n\n@deco\ndef b():\n    """Adds things.\n\n    More text."""\n'
    assert symbols.docs("x.py", py, {0, 4, 8}) == {0: "The module.", 4: "Helps.", 8: "Adds things."}
    ts = "/**\n * Sends an event.\n * @param e the event\n */\nexport function send(e) {}\n\nconst x = 1;\n"
    assert symbols.docs("a.ts", ts, {5, 7}) == {5: "Sends an event."}
    cs = "    /// <summary>\n    /// Makes an invoice.\n    /// </summary>\n    [Obsolete]\n    public void Create() {}\n"
    assert symbols.docs("a.cs", cs, {5}) == {5: "Makes an invoice."}
    assert symbols.docs("a.rs", "/// Adds.\n#[inline]\npub fn add() {}\n", {3}) == {3: "Adds."}
    assert symbols.docs("a.go", "x := 1\n// Handle serves.\nfunc Handle() {}\n", {3}) == {3: "Handle serves."}
    assert symbols.docs("a.py", "def f(:\n", {1}) == {} and symbols.docs("a.py", None, {1}) == {}


def test_your_uncommitted_work_is_mapped_by_folder_and_your_index_is_left_alone(project):
    write(project, BASE)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "base")
    write(project, {"app/billing.py": BASE["app/billing.py"] + '\n\ndef refund(inv):\n    """Gives the money back."""\n    return inv\n',
                    "app/fresh.py": "def fresh():\n    return 1\n", "big.bin": "x" * 1_100_000})
    git(project, "add", "app/billing.py")                                       # one staged change: it must stay staged, and only that
    status, head = git(project, "status", "--porcelain"), git(project, "rev-parse", "HEAD")
    index = (project / ".git" / "index").read_bytes()
    model, why = mindmap.work_model(project)
    assert why == "" and (project / ".git" / "index").read_bytes() == index
    assert git(project, "status", "--porcelain") == status and git(project, "rev-parse", "HEAD") == head
    m = mindmap.build(project, model, "Your uncommitted work")
    assert [b["label"] for b in m["branches"]] == ["app"] and m["tasks"] == []
    syms = {s["qual"]: s for b in m["branches"] for f in b["files"] for s in f["symbols"]}
    assert syms["refund"]["doc"] == "Gives the money back." and syms["refund"]["status"] == "added"
    assert syms["fresh"]["doc"] == "" and "big.bin" not in json.dumps(m)                 # a new file over 1 MB stays off the map
    assert mindmap.work_commit(project)[0] == mindmap.work_commit(project)[0]          # the same files give the same commit
    git(project, "add", "-A")
    git(project, "commit", "-qm", "all")
    assert mindmap.work_model(project) == (None, "Nothing changed since the last commit.")


def test_a_card_is_mapped_by_its_tasks_and_explain_asks_once(project, monkeypatch):
    cid = create_card(project, "Billing discounts").stem
    card_branch(project, BASE, CHANGE, cid=cid)
    app = web.App(project, "main", FakeRunner())
    app.find(cid).set_section("Tasks", "- [x] discounts on invoices [files: app/billing.py]\n- [ ] tax rules [files: app/]\n- [ ] notes for later\n")
    d = app.dispatch("GET", "/api/map", {}, {"src": cid})
    assert d["src"] == cid and d["sources"][0]["id"] == "work" and cid not in {s["id"] for s in d["sources"]}   # a backlog card has no change
    m = d["map"]
    assert [(b["label"], b["done"], [f["path"] for f in b["files"]]) for b in m["branches"]] == [
        ("discounts on invoices", True, ["app/billing.py"]), ("tax rules", False, ["app/tax.py"]), ("notes for later", False, []),
        ("Other changes", None, ["Billing/InvoiceService.cs", "web/http.ts", "web/notifier.ts"])]
    syms = {s["qual"]: s for b in m["branches"] for f in b["files"] for s in f["symbols"]}
    assert "vat" in [x["label"] for x in syms["Invoice.add"]["uses"]] and "sk_live" not in json.dumps(d)
    lines = app.dispatch("GET", "/api/map", {}, {"src": cid, "sym": syms["vat"]["id"]})["lines"]
    assert lines and "sk_live" not in json.dumps(lines)

    asked = []
    from orch import suggest
    monkeypatch.setattr(suggest, "asker", lambda p: lambda prompt: asked.append(prompt) or "  Adds VAT\n to an amount. ")
    explain = {"src": cid, "sym": syms["vat"]["id"]}
    assert app.dispatch("POST", "/api/map/explain", explain, {}) == {"text": "Adds VAT to an amount."}
    assert app.dispatch("POST", "/api/map/explain", explain, {}) == {"text": "Adds VAT to an amount."}
    assert len(asked) == 1 and "def vat(amount):" in asked[0] and "sk_live" not in asked[0]       # asked once, and never with a secret
    module = next(s["id"] for s in syms.values() if s["kind"] == "module")
    for bad in ({"src": cid, "sym": module}, {"src": cid, "sym": "../x"}, {"src": "../x", "sym": syms["vat"]["id"]}):
        with pytest.raises(webcore.Bad):
            app.dispatch("POST", "/api/map/explain", bad, {})
    monkeypatch.setattr(suggest, "asker", lambda p: lambda prompt: None)
    with pytest.raises(webcore.Bad, match="did not answer"):
        app.dispatch("POST", "/api/map/explain", {"src": cid, "sym": syms["Invoice.discount"]["id"]}, {})
