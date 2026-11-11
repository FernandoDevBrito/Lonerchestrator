"""Drawing a change graph (graph.py's model): the terminal tree, one symbol's neighbourhood, Mermaid, Graphviz DOT, and a positioned
layout that the web page and the SVG export share. Pure functions of the model: no git, no files, no network.

The layout is a small layered (Sugiyama-style) one: files are boxes, symbols are rows inside them, an edge leaves the row of the symbol
that uses and enters the row of the symbol that is used; users sit left of what they use. Same model in, same positions out. Collapsing
a file only shortens its box: columns and order are computed from the full heights, so the rest of the map does not move sideways."""
import json
import math

from .safe import clean

W, HEAD, ROW, GAP_X, GAP_Y, PAD, MAX_COL = 300, 46, 22, 120, 28, 40, 2400
MARK = {"added": "+", "removed": "-", "modified": "~", "context": "."}
LETTER = {"added": "A", "removed": "D", "modified": "M", "renamed": "R", "context": " "}
KIND = {"module": "module", "class": "class", "interface": "iface", "enum": "enum", "type": "type", "function": "func", "method": "method",
        "property": "prop", "field": "field", "variable": "var"}
COLOR = {"added": "32", "removed": "31", "modified": "33", "context": "90"}
BOX = {True: {"mid": "|- ", "last": "`- ", "bar": "|  ", "gap": "   ", "on": "#", "off": ".", "ctx": "."},
       False: {"mid": "├─ ", "last": "└─ ", "bar": "│  ", "gap": "   ", "on": "■", "off": "□", "ctx": "·"}}


def safe(model):
    """A copy whose every string has no control or bidi characters: file names come from git and a repository can hold any name, so
    nothing from the model may reach a terminal (or an SVG) as an escape sequence."""
    def walk(v):
        return clean(v) if isinstance(v, str) else [walk(x) for x in v] if isinstance(v, list) else {k: walk(x) for k, x in v.items()} if isinstance(v, dict) else v
    return walk(json.loads(json.dumps(model)))


def _paint(text, code, color):
    return f"\x1b[{code}m{text}\x1b[0m" if color and code else text


def _cut(s, n):
    return s if len(s) <= n else s[:max(n - 2, 1)] + ".."


def bar(bucket, ascii_only=False):
    g = BOX[ascii_only]
    return g["on"] * bucket + g["off"] * (5 - bucket)


def _index(model):
    syms = {s["id"]: (f, s) for f in model["files"] for s in f["symbols"]}
    outs, ins = {}, {}
    for e in model["edges"]:
        if e["from"] in syms and e["to"] in syms:
            outs.setdefault(e["from"], []).append(e)
            ins.setdefault(e["to"], []).append(e)
    return syms, outs, ins


def _short(syms, sid, here):
    f, s = syms[sid]
    return (s["qual"] or "module level") + ("" if f["path"] == here else f" ({f['path']})")


def _edge_lines(syms, sid, outs, ins, here):
    """`-> calls vat (app/tax.py) +new`, `<- used by monthly (app/report.py)`: what a symbol uses and what uses it."""
    lines = []
    by = {}
    for e in outs.get(sid, ()):
        by.setdefault(e["kind"], []).append(_short(syms, e["to"], here) + {"added": " +new", "removed": " -gone"}.get(e["status"], ""))
    lines += [f"-> {k} {', '.join(v)}" for k, v in sorted(by.items())]
    users = {}
    for e in ins.get(sid, ()):
        users.setdefault("tested by" if e["kind"] == "tests" else "used by", []).append(_short(syms, e["from"], here) + {"added": " +new", "removed": " -gone"}.get(e["status"], ""))
    users = {k: list(dict.fromkeys(v)) for k, v in users.items()}                 # one user that reads and writes is listed once
    lines += [f"<- {k} {', '.join(v) if len(v) <= 4 else f'{len(v)}: ' + ', '.join(v[:3]) + ', ...'}" for k, v in sorted(users.items())]
    return lines


def tree(model, color=False, ascii_only=False, width=80, edges=True):
    """The graph as text: files grouped by directory, one line per symbol with its churn bar, and under it what it uses and what uses it.
    Works in a pipe and at 80 columns; `color` adds ANSI colours, `ascii_only` swaps the box and block characters for plain ones."""
    g = BOX[ascii_only]
    model = safe(model)
    syms, outs, ins = _index(model)
    snap, st = model.get("snapshot", {}), model["stats"]
    out = [_cut(_summary(model), width), _cut(f"card {snap.get('cardId') or '-'}" + (f", attempt {snap['attempt']}" if snap.get("attempt") else "") +
                                         f", {snap.get('source', '')} {str(snap.get('head', ''))[:10]} against {str(snap.get('base', ''))[:10]}, +{st['added']} -{st['removed']}", width)]
    for msg in model.get("guardrails", []):
        out.append(_paint(_cut(f"! {msg}", width), "31", color))
    for fd in model.get("findings", []):
        out.append(_paint(_cut(f"? {fd['reviewer']} ({fd['severity']}): {fd['text']}", width), "35", color))
    by_id = {f["id"]: f for f in model["files"]}
    for grp in model["groups"]:
        out.append("")
        out.append(_paint(_cut(grp["label"] + "/", width), "1", color))
        for f in (by_id[i] for i in grp["fileIds"] if i in by_id):
            right = "unchanged" if f["status"] == "context" else f"{LETTER.get(f['status'], ' ')}  +{f['added']} -{f['removed']}"
            name = f["path"].rsplit("/", 1)[-1] + (f"  (was {f['oldPath']})" if f.get("oldPath") else "")
            out.append("  " + _cut(name, width - len(right) - 4).ljust(width - len(right) - 3) + " " + right)
            for note in [f["note"]] if f.get("note") else []:
                out.append(_cut(f"    {note}", width))
            for x in f["guardrails"]:
                out.append(_paint(_cut(f"    ! {x}", width), "31", color))
            kids = {}
            ids = {s["id"] for s in f["symbols"]}
            for s in f["symbols"]:
                kids.setdefault(s["parent"] if s["parent"] in ids else None, []).append(s)

            def walk(parent, prefix, kids=kids, f=f):
                items = kids.get(parent, [])
                for i, s in enumerate(items):
                    last = i == len(items) - 1
                    lead = prefix + (g["last"] if last else g["mid"])
                    stem = prefix + (g["gap"] if last else g["bar"])
                    mark = g["ctx"] if s["status"] == "context" else MARK[s["status"]]
                    tags = (" [hotspot]" if s.get("hotspot") else "") + (" [moved]" if s.get("moved") else "") + \
                           (f" [was {s['from']['qual']}]" if s.get("from") else "") + (f" [{s['delta']}]" if s.get("delta", "same") != "same" else "")
                    nums = "unchanged" if s["status"] == "context" else f"+{s['added']} -{s['removed']} {bar(s['churnBucket'], ascii_only)}"
                    left = f"{lead}{mark} {KIND.get(s['kind'], s['kind']):<6} {s['name'] if s['kind'] != 'module' else 'Module level'}{tags}"
                    room = width - 2 - len(nums) - 1
                    line = _cut(left, room).ljust(room) + " " + nums
                    code = "1;" + COLOR[s["status"]] if s.get("hotspot") else COLOR[s["status"]]
                    out.append("  " + _paint(line, code, color))
                    sub = stem + (g["bar"] if kids.get(s["id"]) else g["gap"])
                    for x in s["guardrails"]:
                        out.append("  " + _paint(_cut(f"{sub}! {x}", width - 2), "31", color))
                    for fd in s["findings"]:
                        out.append("  " + _paint(_cut(f"{sub}? {fd['reviewer']}: {fd['text']}", width - 2), "35", color))
                    if edges:
                        for ln in _edge_lines(syms, s["id"], outs, ins, f["path"]):
                            out.append("  " + _paint(_cut(f"{sub}  {ln}", width - 2), "36" if "+new" in ln else "", color))
                    walk(s["id"], stem, kids, f)
            walk(None, "    ")
    out.append("")
    out.append(f"{st['files']} files, {st['symbols']} rows")
    return "\n".join(out)


def _summary(model):
    from .graph import summary_line
    return summary_line(model)


def ego(model, focus, ascii_only=False, width=80):
    """One symbol and its direct neighbours, drawn with box characters: what uses it above, what it uses below."""
    g = BOX[ascii_only]
    model = safe(model)
    syms, outs, ins = _index(model)
    hits = [i for i, (f, s) in syms.items() if focus in (i, s["name"], s["qual"])]
    if not hits:
        return f"no symbol called '{focus}' in this graph"
    blocks = []
    h, v, tl, tr, bl, br = ("-", "|", "+", "+", "+", "+") if ascii_only else ("─", "│", "┌", "┐", "└", "┘")
    for sid in hits:
        f, s = syms[sid]
        rows = [f"{MARK.get(s['status'], '.')} {s['qual'] or 'module level'}  ({KIND.get(s['kind'], s['kind'])})",
                f"{f['path']}:{s['range']['start']}  " + ("unchanged" if s["status"] == "context" else f"+{s['added']} -{s['removed']} {bar(s['churnBucket'], ascii_only)}")
                + ("  hotspot" if s.get("hotspot") else "")]
        inner = min(width - 6, max(len(r) for r in rows) + 2)
        lines = []
        users = [(_cut(_short(syms, e["from"], ""), width - 30), e) for e in ins.get(sid, ())]
        pad = max((len(u) for u, _ in users), default=0)
        for u, e in users:
            lines.append(f"  {u.ljust(pad)}  {h * 2} {e['kind']} {h * 2}>" + {"added": "  (new)", "removed": "  (gone)"}.get(e["status"], ""))
        if ins.get(sid):
            lines.append(f"  {' ' * 4}{v}")
        lines.append(f"  {tl}{h * inner}{tr}")
        lines += [f"  {v} {_cut(r, inner - 2).ljust(inner - 2)} {v}" for r in rows]
        lines.append(f"  {bl}{h * inner}{br}")
        es = outs.get(sid, [])
        for i, e in enumerate(es):
            lead = g["last"] if i == len(es) - 1 else g["mid"]
            lines.append(f"    {lead}{e['kind']} {h}> {_cut(_short(syms, e['to'], ''), width - 22)}" + {"added": "  (new)", "removed": "  (gone)"}.get(e["status"], ""))
        if not ins.get(sid) and not es:
            lines.append("    (no edges: nothing in the change uses it or is used by it)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _q(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def mermaid(model):
    """A Mermaid flowchart (paste it in a PR or a README): a subgraph per file, a node per symbol. New edges are thick, removed ones dotted."""
    out = ["flowchart LR"]
    model = safe(model)
    for f in model["files"]:
        out.append(f'  subgraph f{f["id"]}["{_mq(f["path"])}"]')
        for s in f["symbols"]:
            out.append(f'    s{s["id"]}["{MARK.get(s["status"], ".")} {KIND.get(s["kind"], s["kind"])} {_mq(s["qual"] or "module level")}"]:::{s["status"]}')
        out.append("  end")
    arrow = {"added": "==>", "removed": "-.->", "kept": "-->"}
    out += [f'  s{e["from"]} {arrow.get(e["status"], "-->")}|{e["kind"]}| s{e["to"]}' for e in model["edges"]]
    out += ["  classDef added stroke:#2f855a,stroke-width:2px", "  classDef removed stroke:#c53030,stroke-dasharray:4 3",
            "  classDef modified stroke:#b7791f,stroke-width:2px", "  classDef context stroke:#a1a1aa,color:#71717a"]
    return "\n".join(out)


def _mq(text):
    return str(text).replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def dot(model):
    """Graphviz DOT (`dot -Tsvg`): a cluster per file, a node per symbol, edge width by weight."""
    pen = {"added": "#2f855a", "removed": "#c53030", "modified": "#b7791f", "context": "#a1a1aa"}
    model = safe(model)
    out = ["digraph change {", "  rankdir=LR;", '  node [shape=box, fontname="Helvetica", fontsize=10];', '  edge [fontname="Helvetica", fontsize=9];']
    for f in model["files"]:
        out.append(f'  subgraph "cluster_{f["id"]}" {{ label="{_q(f["path"])}";')
        for s in f["symbols"]:
            out.append(f'    "{s["id"]}" [label="{MARK.get(s["status"], ".")} {_q(KIND.get(s["kind"], s["kind"]))} {_q(s["qual"] or "module level")}", color="{pen[s["status"]]}"'
                       + (", penwidth=2" if s.get("hotspot") else "") + "];")
        out.append("  }")
    for e in model["edges"]:
        out.append(f'  "{e["from"]}" -> "{e["to"]}" [label="{e["kind"]}", penwidth={1 + math.log2(e["weight"]):.1f}'
                   + {"added": ', color="#2f855a"', "removed": ', style=dashed, color="#c53030"'}.get(e["status"], "") + "];")
    out.append("}")
    return "\n".join(out)


# ---------------------------------------------------------------- layout

def layout(model, collapsed=()):
    """Positions for every file box, symbol row and edge: {"width", "height", "files": {id: {x, y, h, collapsed, rows: {symbol id: y}}},
    "edges": [{"from", "to", "d"}]} (d = an SVG path). Deterministic; see the module docstring for what collapsing keeps still."""
    files = sorted(model["files"], key=lambda f: f["path"])
    owner = {s["id"]: f["id"] for f in files for s in f["symbols"]}
    succ = {f["id"]: set() for f in files}
    for e in model["edges"]:
        a, b = owner.get(e["from"]), owner.get(e["to"])
        if a and b and a != b:
            succ[a].add(b)
    order = [f["id"] for f in files]
    # break cycles: an edge back to a file still on the DFS path is ignored for the layering
    dag, state = {n: set() for n in order}, {}

    def dfs(n):
        state[n] = 1
        for m in sorted(succ[n], key=order.index):
            if state.get(m) == 1:
                continue
            dag[n].add(m)
            if m not in state:
                dfs(m)
        state[n] = 2
    for n in order:
        if n not in state:
            dfs(n)
    layer = {}
    preds = {n: [p for p in order if n in dag[p]] for n in order}

    def depth(n, seen=()):
        if n not in layer:
            layer[n] = 0 if not preds[n] else 1 + max(depth(p) for p in preds[n])
        return layer[n]
    for n in order:
        depth(n)
    full = {f["id"]: HEAD + ROW * len(f["symbols"]) + 8 for f in files}
    cols = {}
    for n in order:
        cols.setdefault(layer[n], []).append(n)
    # order inside each layer: by directory and path, then a few barycenter sweeps toward the neighbours' positions
    pos = {n: i for c in cols.values() for i, n in enumerate(c)}
    for sweep in range(4):
        keys = sorted(cols) if sweep % 2 == 0 else sorted(cols, reverse=True)
        for k in keys:
            def bary(n, k=k, sweep=sweep):
                nb = preds[n] if sweep % 2 == 0 else list(dag[n])
                nb = [m for m in nb if layer[m] != k]
                return (sum(pos[m] for m in nb) / len(nb)) if nb else pos[n]
            cols[k].sort(key=lambda n, bary=bary: (bary(n), pos[n]))
            for i, n in enumerate(cols[k]):
                pos[n] = i
    # a tall layer wraps into several columns (from the full heights, so collapsing never moves a box sideways)
    slots, x = {}, 0
    for k in sorted(cols):
        used = 0
        for n in cols[k]:
            if used and used + full[n] > MAX_COL:
                x, used = x + 1, 0
            slots[n] = x
            used += full[n] + GAP_Y
        x += 1
    shut = set(collapsed)
    out, heights = {}, {}
    for n in order:
        heights[n] = HEAD if n in shut else full[n]
    y_at = {}
    by_id = {f["id"]: f for f in files}
    for n in sorted(order, key=lambda n: (slots[n], layer[n], pos[n])):
        y = y_at.get(slots[n], PAD)
        f = by_id[n]
        rows = {s["id"]: (y + HEAD / 2 if n in shut else y + HEAD + ROW * i + ROW / 2) for i, s in enumerate(f["symbols"])}
        out[n] = {"x": PAD + slots[n] * (W + GAP_X), "y": y, "h": heights[n], "collapsed": n in shut, "rows": rows}
        y_at[slots[n]] = y + heights[n] + GAP_Y
    edges = []
    for e in model["edges"]:
        a, b = owner.get(e["from"]), owner.get(e["to"])
        if not a or not b:
            continue
        s, t = out[a], out[b]
        sy, ty = s["rows"][e["from"]], t["rows"][e["to"]]
        if a == b:
            x0 = s["x"] + W
            d = f"M{x0},{sy:.0f} C{x0 + 40},{sy:.0f} {x0 + 40},{ty:.0f} {x0},{ty:.0f}"
        elif t["x"] > s["x"]:
            x0, x1 = s["x"] + W, t["x"]
            dx = max(40, (x1 - x0) / 2)
            d = f"M{x0},{sy:.0f} C{x0 + dx:.0f},{sy:.0f} {x1 - dx:.0f},{ty:.0f} {x1},{ty:.0f}"
        elif t["x"] == s["x"]:
            x0 = s["x"] + W
            d = f"M{x0},{sy:.0f} C{x0 + 70},{sy:.0f} {x0 + 70},{ty:.0f} {x0},{ty:.0f}"
        else:
            x0, x1 = s["x"], t["x"] + W
            dx = max(40, (x0 - x1) / 2)
            d = f"M{x0},{sy:.0f} C{x0 - dx:.0f},{sy:.0f} {x1 + dx:.0f},{ty:.0f} {x1},{ty:.0f}"
        edges.append({"from": e["from"], "to": e["to"], "d": d})
    width = PAD * 2 + (max((v["x"] for v in out.values()), default=0) - PAD) + W + (70 if edges else 0)
    height = max((v["y"] + v["h"] for v in out.values()), default=0) + PAD
    return {"width": width, "height": height, "w": W, "head": HEAD, "row": ROW, "files": out, "edges": edges}


def _x(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def svg(model, lay=None):
    """A standalone SVG of the graph (same layout as the web page): no script, no external file, light and dark colours."""
    lay = lay or layout(model)
    model = safe(model)
    st = model["stats"]
    css = (":root{--bg:#fafafa;--dot:#d4d4d8;--box:#fff;--line:#d4d4d8;--fg:#18181b;--mute:#71717a;--add:#2f855a;--del:#c53030;--mod:#b7791f;--edge:#2f855a}"
           "@media (prefers-color-scheme:dark){:root{--bg:#09090b;--dot:#27272a;--box:#18181b;--line:#3f3f46;--fg:#f4f4f5;--mute:#a1a1aa;--add:#4ade80;--del:#f87171;--mod:#fbbf24;--edge:#4ade80}}"
           "text{font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:var(--fg)}.m{fill:var(--mute)}.h{font-weight:600}"
           ".added{fill:var(--add)}.removed{fill:var(--del)}.modified{fill:var(--mod)}.context{fill:var(--mute)}"
           ".e{fill:none;stroke:var(--edge);stroke-opacity:.45}.e.removed{stroke:var(--del);stroke-dasharray:4 3}.e.added{stroke-opacity:.8}"
           "rect.f{fill:var(--box);stroke:var(--line)}rect.g{stroke:var(--del);stroke-width:2}")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{lay["width"]}" height="{lay["height"]}" viewBox="0 0 {lay["width"]} {lay["height"]}" '
           f'role="img" aria-label="Change graph: {st["files"]} files, {st["changes"]} changes">',
           f"<title>{_x(_summary(model))}</title><style>{css}</style>",
           '<defs><pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" style="fill:var(--dot)"/></pattern></defs>',
           '<rect width="100%" height="100%" style="fill:var(--bg)"/><rect width="100%" height="100%" fill="url(#dots)"/>']
    status = {e["from"] + e["to"]: e for e in model["edges"]}
    for e in lay["edges"]:
        m = status.get(e["from"] + e["to"], {})
        out.append(f'<path class="e {m.get("status", "")}" d="{e["d"]}" stroke-width="{1 + math.log2(m.get("weight", 1)):.1f}"><title>{_x(m.get("kind", ""))}</title></path>')
    for f in model["files"]:
        box = lay["files"][f["id"]]
        x, y = box["x"], box["y"]
        hit = " g" if f["guardrails"] or any(s["guardrails"] for s in f["symbols"]) else ""
        out.append(f'<g><rect class="f{hit}" x="{x}" y="{y}" width="{W}" height="{box["h"]}" rx="4"/>')
        out.append(f'<text class="h" x="{x + 10}" y="{y + 19}">{_x(_cut(f["path"].rsplit("/", 1)[-1], 34))}</text>'
                   f'<text class="{f["status"] if f["status"] in MARK else "m"}" x="{x + W - 10}" y="{y + 19}" text-anchor="end">{LETTER.get(f["status"], "")}</text>')
        out.append(f'<text class="m" x="{x + 10}" y="{y + 36}">{_x(_cut(f["path"].rsplit("/", 1)[0] if "/" in f["path"] else ".", 40))}</text>')
        if not box["collapsed"]:
            depth = {}
            for s in f["symbols"]:
                depth[s["id"]] = depth.get(s["parent"], -1) + 1 if s["parent"] else 0
                cy = box["rows"][s["id"]]
                ind = 10 + 12 * depth[s["id"]]
                out.append(f'<text class="{s["status"]}" x="{x + ind}" y="{cy + 4:.0f}">{MARK.get(s["status"], ".")}</text>'
                           f'<text x="{x + ind + 14}" y="{cy + 4:.0f}">{_x(_cut(s["name"] if s["kind"] != "module" else "Module level", 26 - 2 * depth[s["id"]]))}'
                           f'<title>{_x(s["kind"])} {_x(s["qual"])}</title></text>')
                for i in range(5):
                    on = i < s["churnBucket"]
                    out.append(f'<rect x="{x + W - 52 + i * 8}" y="{cy - 3:.0f}" width="6" height="6" class="{s["status"] if on else "context"}" '
                               f'style="opacity:{1 if on else .25}"/>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- `lonerchestrator graph --tui`: one frame, from the model and a small state

def outline(model):
    """[(depth, file, symbol or None)] in the order `tree` prints them: a file row, then its symbols under their parents."""
    rows, by_id = [], {f["id"]: f for f in model["files"]}
    for grp in model["groups"]:
        for f in (by_id[i] for i in grp["fileIds"] if i in by_id):
            rows.append((0, f, None))
            ids, kids = {s["id"] for s in f["symbols"]}, {}
            for s in f["symbols"]:
                kids.setdefault(s["parent"] if s["parent"] in ids else None, []).append(s)
            stack = [(s, 1) for s in reversed(kids.get(None, []))]
            while stack:
                s, d = stack.pop()
                rows.append((d, f, s))
                stack += [(k, d + 1) for k in reversed(kids.get(s["id"], []))]
    return rows


HELP = "j/k move  Enter diff  space fold  f focus  / search  Esc clear  q quit"


def visible(model, st):
    """The outline without the symbols of folded files."""
    return [r for r in outline(model) if r[2] is None or r[1]["id"] not in st["fold"]]


def frame(model, st, width, height, color=True):
    """The screen as text: the outline around the cursor, the diff of every opened symbol under it, a status line.
    st: {"cur": row index, "open": symbol ids, "fold": file ids, "focus": "", "query": "", "typing": None or the search being typed}."""
    from .graph import lines_of, summary_line
    model = safe(model)
    rows = visible(model, st)
    st["cur"] = max(0, min(st["cur"], len(rows) - 1))
    lines, at = [], 0
    for i, (d, f, s) in enumerate(rows):
        if i == st["cur"]:
            at = len(lines)
        if s is None:
            text = f"{'+' if f['id'] in st['fold'] else '-'} {f['path']}  {LETTER.get(f['status'], ' ')} +{f['added']} -{f['removed']}" + (f"  ! {', '.join(f['guardrails'])}" if f["guardrails"] else "")
            code = "1"
        else:
            nums = "unchanged" if s["status"] == "context" else f"+{s['added']} -{s['removed']} {bar(s['churnBucket'])}"
            tags = (" [hotspot]" if s.get("hotspot") else "") + (" !" if s["guardrails"] else "") + (" ?" if s["findings"] else "")
            text = f"{'  ' * d}{MARK[s['status']]} {KIND.get(s['kind'], s['kind']):<6} {s['name'] if s['kind'] != 'module' else 'Module level'}{tags}"
            text = _cut(text, width - len(nums) - 2).ljust(width - len(nums) - 2) + " " + nums
            code = COLOR[s["status"]]
        lines.append(_paint(_cut(text, width - 1), "7" if i == st["cur"] else code, color))
        if s is not None and s["id"] in st["open"]:
            for o, n, ln in lines_of(model, s["id"]) or [(None, None, "  (no diff lines: the symbol did not change)")]:
                tag = ln[:1]
                lines.append(_paint(_cut(f"      {o or '':>5} {n or '':>5} {ln}", width - 1), {"+": "32", "-": "31"}.get(tag, "90"), color))
            for x in s["guardrails"] + [f"{fd['reviewer']}: {fd['text']}" for fd in s["findings"]]:
                lines.append(_paint(_cut(f"      {x}", width - 1), "35", color))
    body = height - 3
    top = max(0, min(at - body // 2, len(lines) - body))
    head = summary_line(model) + (f"   focus: {st['focus']}" if st.get("focus") else "") + (f"   search: {st['query']}" if st.get("query") else "")
    foot = f"/{st['typing']}" if st.get("typing") is not None else HELP
    return "\n".join([_paint(_cut(head, width - 1), "1", color), *lines[top:top + body], *[""] * max(0, body - len(lines[top:top + body])),
                      _paint(_cut(foot, width - 1), "90", color)])
