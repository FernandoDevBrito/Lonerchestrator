"""The Change graph view of the web page: one card's diff as a graph of the symbols it changed (graph.py), filtered and laid out
(graphview.py). It only reads: saved snapshots under .orchestrator/runs, or git. Every query value is checked or clamped here."""
import json
import re

from . import config, graph, graphview
from .webcore import Bad, route

MAX_DRAW = 600                     # symbols after the filters; above it the page shows the list and asks for a filter
STATUSES = ("added", "removed", "modified", "context")
SYMBOL = re.compile(r"^[0-9a-f]{12}$")
EXPORTS = {"svg": ("svg", graphview.svg), "mermaid": ("mmd", graphview.mermaid), "dot": ("dot", graphview.dot),
           "json": ("json", lambda m: json.dumps(m, indent=2, ensure_ascii=False))}


def _csv(q, key, allowed):
    return [v for v in (q.get(key) or "").split(",") if v in allowed]


class GraphApi:
    @route("GET", "/api/graph/", takes="tailq")
    def change_graph(self, cid, q):
        """?snap=<run>/<attempt>  ?compare=<key>..<key>  ?only=added,modified  ?hide=context,tests  ?findings=1  ?guardrails=1
        ?focus=<name or id>&depth=1..3  ?q=<text>  ?fold=<file id>,...  ?format=svg|mermaid|dot|json (a file to save)  ?format=lines&sym=<id>"""
        c = self.find(cid)
        cfg = config.load(self.project)
        snaps = graph.snapshots(self.project, c.id)
        keys = [s["key"] for s in snaps]
        key = q.get("snap") or ""
        if q.get("compare"):
            a, _, b = q["compare"].partition("..")
            if a not in keys or b not in keys or a == b:
                raise Bad("compare takes two different saved attempts of this card")
            model, key = graph.compare(graph.read(self.project, c.id, a), graph.read(self.project, c.id, b)), b
        else:
            if key and key not in keys:
                raise Bad("this card has no such attempt", 404)
            model, _ = graph.load(self.project, c.id, self.base, cfg["guardrails"], key or None)
            key = key or (keys[-1] if keys else "")
        head = {"card": c.id, "title": c.title, "state": c.path.parent.name, "snapshots": snaps, "key": key}
        if model is None:
            return {**head, "model": None}
        if q.get("format") == "lines":
            if not SYMBOL.match(q.get("sym") or ""):
                raise Bad("bad symbol id")
            return {"lines": graph.lines_of(model, q["sym"])}
        depth = int(q["depth"]) if (q.get("depth") or "").isdigit() else 1
        shown = graph.view(model, only=_csv(q, "only", STATUSES), hide=_csv(q, "hide", ("context", "tests")), findings=q.get("findings") == "1",
                           guardrails=q.get("guardrails") == "1", focus=(q.get("focus") or "")[:200], depth=min(max(depth, 1), 3), query=(q.get("q") or "")[:200])
        if q.get("format") in EXPORTS:
            ext, draw = EXPORTS[q["format"]]
            return {"name": f"{c.id}-graph.{ext}", "text": draw(shown)}
        big = shown["stats"]["symbols"] > MAX_DRAW
        for f in shown["files"]:
            f["hunks"] = []                # the side panel asks for one symbol's lines (format=lines): the page never holds the whole diff
        fold = [i for i in (q.get("fold") or "").split(",") if SYMBOL.match(i)]          # file ids are the same 12 hex digits
        return {**head, "model": shown, "layout": None if big else graphview.layout(shown, collapsed=fold), "total": model["stats"], "too_big": big, "max": MAX_DRAW}
