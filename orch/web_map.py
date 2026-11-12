"""The Map view of the web page: a change as a mind map (mindmap.py). Your uncommitted work, or any card that got past the backlog.
It only reads, except Explain: one read-only call to the suggester AI, made when you click it."""
from . import config, graph, mindmap
from .board import STATES
from .web_graph import SYMBOL
from .webcore import Bad, route

WORK = "work"


class MapApi:
    def _change(self, src):
        """(title, tasks text, model, why) of a source: "work" or a card id."""
        guard = config.load(self.project)["guardrails"]
        if src == WORK:
            return "Your uncommitted work", "", *mindmap.work_model(self.project, guard)
        c = self.find(src)
        model, _ = graph.load(self.project, c.id, self.base, guard)
        return c.title, c.section("Tasks"), model, "" if model else "This card has no change yet."

    @route("GET", "/api/map", takes="query")
    def code_map(self, q):
        """?src=work|<card id> (default work)   ?sym=<id>: that symbol's diff lines instead of the map"""
        src = q.get("src") or WORK
        title, tasks, model, why = self._change(src)
        if q.get("sym"):
            if not SYMBOL.match(q["sym"]):
                raise Bad("bad symbol id")
            return {"lines": graph.lines_of(model, q["sym"]) if model else []}
        sources = [{"id": WORK, "title": "Your uncommitted work", "state": ""}]
        sources += [{"id": c.id, "title": c.title, "state": s} for s in STATES if s != "backlog" for c in self.board.cards(s)]
        return {"src": src, "sources": sources, "why": why, "map": mindmap.build(self.project, model, title, tasks)}

    @route("POST", "/api/map/explain", takes="body")
    def explain_symbol(self, body):
        """{"src": "work" or a card id, "sym": <id>} -> {"text": one or two sentences}"""
        if not SYMBOL.match(str(body.get("sym") or "")):
            raise Bad("bad symbol id")
        _, _, model, _ = self._change(str(body.get("src") or WORK))
        if model is None or mindmap.code_of(self.project, model, body["sym"]) is None:
            raise Bad("that is not a changed function or class of this change", 404)
        text = mindmap.explain(self.project, model, body["sym"])
        if not text:
            raise Bad("The suggester AI did not answer. Check that it is installed and signed in (AIs tab), and its role (Settings).", 502)
        return {"text": text}
