# Change graph

A card's diff drawn as the functions, classes and files it changed, and the code that uses them or is used by them. It answers a
reviewer's first questions before they read the diff line by line: *what did this touch, what depends on it, where do I start?*

It only shows. It never approves, blocks or changes a card: the guardrails (`orch/guardrails.py`) and the reviewers decide, the
graph only lays their findings where they point. Everything is local and standard library: git plumbing, Python's `ast`, regular
expressions. No network, no API key, no telemetry, and the analysed project's code is never run.

    git diff -> files and hunks -> symbols (orch/symbols.py) -> edges -> the model (versioned JSON, orch/graph.py)
             -> terminal tree, ego view, Mermaid, DOT, SVG, positioned layout (orch/graphview.py) -> web page (orch/web_graph.py, app.js)

## Using it

**Terminal.** `lonerchestrator graph <card>` prints the tree: one block per file, its changed symbols (`+` added, `-` removed,
`~` modified, `.` unchanged neighbour), a churn bar and the edges of each symbol.

```bash
lonerchestrator graph 005                          # the latest attempt (card id or its number)
lonerchestrator graph 005 --attempt 1              # an earlier attempt
lonerchestrator graph 005 --compare 1..2           # what the fix loop changed between attempts 1 and 2
lonerchestrator graph 005 --focus csv_rows --depth 2                  # one symbol and everything up to two edges away
lonerchestrator graph 005 --focus csv_rows --format ascii             # that symbol and its direct neighbours, as boxes
lonerchestrator graph 005 --only added,modified --hide tests
lonerchestrator graph 005 --findings               # only symbols a reviewer flagged (--guardrails: only guardrail hits)
lonerchestrator graph 005 --format mermaid --out graph.mmd            # also json, dot, svg
lonerchestrator graph 005 --tui                    # browse: j/k, Enter = the symbol's diff, space folds a file,
                                                   # f = its neighbourhood, / = search, Esc = clear, q = quit
```

`--ascii` (or `TERM=dumb`) draws with plain characters, `NO_COLOR` turns colour off.

**Web page** (`lonerchestrator web`). Open a card that has started and press **Change graph** (or `g`). Files are boxes,
changed symbols are rows, an edge runs from the user to what it uses. Click a row for its side panel: where it is, what it uses,
what uses it, reviewer findings, guardrail hits and its own diff lines. **Focus here** keeps that symbol and its neighbours. The
**View** menu filters by status, tests, findings and guardrails; **Export** saves SVG, Mermaid, DOT or JSON; **List** shows the
same content as text (also the fallback above 600 symbols). Keys inside the graph: drag to pan, wheel or `+` `-` to zoom,
`f` fit, `l` list, `/` search, `Esc` back. The address bar is always a link to the exact view: `?graph=<card>` opens it, and the
hash carries `sel`, `focus`, `depth`, `only`, `hide`, `findings`, `guardrails`, `q`, `fold`, `snap`, `compare` and `view`.

**Reviewers.** With `"graph": {"review_summary": true}` the reviewers' input also gets a short summary computed from the diff
(hotspots, dependencies added or removed, edges between top-level directories, guardrail hits) under `# CHANGE GRAPH`. It is off by
default, so the reviewers' input is unchanged unless you opt in. It never contains the builder's own words.

**Config** (`.orchestrator/config.json`, also in the Settings tab):

```json
{ "graph": { "enabled": true, "review_summary": false } }
```

`enabled: false` stops the pipeline from saving graphs. `lonerchestrator graph` and the web page still build one from the card's
branch when asked.

## Where a graph comes from

1. **The pipeline.** Every attempt, right after the guardrails have checked the staged change (pass or fail; `orch/stages.py`,
   `draw`), the graph of that diff against the base branch is saved as `.orchestrator/runs/<run>/<card>/graph<attempt>.json`.
   Each reviewer's output of that attempt is saved next to it as `review<attempt>-<reviewer>.txt`. If building the graph fails, the error is logged and the card
   carries on.
2. **Git, when no attempt saved one.** The card's branch `card/<id>` against where it left the base, else the merge commit
   `Merge card <id>:` on the base. Built on demand and kept in a small in-memory cache.

Reading a saved attempt also reads that attempt's reviews: every bullet under `FAILURES` becomes a finding on the symbol that a
`path:line` in it points at, on the file a bare path names, or on the graph as a whole. That is why the qa and Gemini instructions
ask for `path:line` in each failure.

## The model (schemaVersion 1)

One JSON document per snapshot. `graph.dumps` writes it deterministically: the same change gives the same bytes, except
`snapshot.createdAt`. The numbers below are the demo change of the README pictures (`docs/screenshots.py`, card 005).

```jsonc
{
  "schemaVersion": 1,
  "snapshot": {"cardId": "005-order-export-csv", "attempt": 1, "base": "<commit>", "head": "<commit, or the staged tree>",
               "source": "pipeline | branch | merge | staged | commit", "createdAt": "2026-11-11T01:56:07"},
  "stats": {"files": 5, "symbols": 13, "changes": 11, "added": 39, "removed": 0, "edges": 13, "hotspots": 3, "findings": 0, "guardrails": 0},
  "files": [{
    "id": "<12 hex>", "path": "api/export.py", "oldPath": null, "lang": "python",
    "status": "added | removed | modified | renamed | context",
    "added": 18, "removed": 0,                        // changed lines of the whole file
    "note": "",                                       // why the file got less than a full outline, e.g. "protected file: content not shown"
    "guardrails": [],                                 // hits anchored to the file
    "hunks": [{"old": 1, "new": 1, "lines": ["+..."]}],// the diff, secrets redacted; [] above 3000 lines or for a protected file
    "symbols": [{
      "id": "<12 hex>", "name": "csv_rows", "qual": "csv_rows",        // qual = Class.method for members, "" for the module row
      "kind": "module | class | interface | enum | type | function | method | property | field | variable",
      "status": "added | removed | modified | context",
      "range": {"start": 10, "end": 18},                               // 1-based, inclusive; "side": "old" for a removed symbol
      "added": 9, "removed": 0, "churnBucket": 2, "degree": 6, "hotspot": true,
      "parent": null,                                                  // the parent symbol's id (a method's class)
      "findings": [{"reviewer": "qa", "severity": "blocking | note", "text": "...", "line": 14}],
      "guardrails": ["possible secret in added line 14"],
      "from": {"path": "api/old.py", "qual": "rows"},                  // only on a rename or move
      "moved": true                                                    // only when the body is the same, just elsewhere
    }]
  }],
  "edges": [{"from": "<symbol id>", "to": "<symbol id>", "kind": "calls", "status": "added | removed | kept", "weight": 2}],
  "groups": [{"id": "<12 hex>", "label": "api", "fileIds": ["..."]}], // files by directory
  "guardrails": ["31 files changed, limit 25"],                         // hits that belong to no file
  "findings": []                                                        // findings that name no file of the graph
}
```

`compare` (two attempts) returns the newer model plus `delta` on every symbol and edge (`new`, `changed`, `same`, `gone`; gone
ones are put back so they show) and `compare: {from, to}` with both snapshots.

## How it is computed

**Files.** `git diff -M --full-index -U3` between the base and the change (the index for the pipeline, a commit otherwise; for a
commit, from where the two histories meet). File contents come from `git cat-file --batch`, never a checkout.

**Symbols.** Python is parsed exactly by `ast`; a file that does not parse gets an outline from its `def` and `class` lines.
JavaScript, TypeScript, C#, Java, Kotlin, Swift, Go, Rust and PHP get an outline from declaration patterns plus brace matching,
after comments and strings are blanked: good enough to put a changed line inside the right function, not a compiler. Every file
also has a *Module level* row for lines outside any symbol. A file the graph cannot outline (unknown language, binary, generated,
minified, a lock file, bigger than 1 MB) is that one row, with a `note` saying why.

**Status of a symbol.** In both versions with changed lines inside its range: `modified`. Only in the new version: `added`. Only
in the old one: `removed`. Unchanged: `context` (shown only when an edge needs it). A removed and an added symbol of the same kind
whose bodies match with a `difflib` ratio of at least 0.8 (sizes within 2x of each other) are one renamed or moved symbol:
status `modified` with `from`; `moved` when the body is identical.

**Edges.** Each line's uses (calls, reads, writes, type references, base classes, imports) are resolved to a symbol: precise first
(the file's imports, the same file, the same class and its bases), then by name only when exactly one symbol in the graph has that
name and it is not a common one (`get`, `run`, `items`, ...). Kinds:

| kind | when |
| --- | --- |
| `imports` | an import of a symbol or module |
| `extends`, `implements` | a base class or an interface |
| `calls` | a call, or a reference to a function or method |
| `reads`, `writes` | a use of, or a store into, a variable, field or property |
| `typeref` | a class or type used without calling it (an annotation, a signature) |
| `tests` | a `calls` or `reads` from a test file |

An edge is drawn when at least one end changed. Its `status` says whether the change `added` it, `removed` it or `kept` it, and
`weight` is how many times it is used. An import the change did not touch is left out as noise.

**Context.** One hop of unchanged code: up to 40 unchanged files that mention a changed name (or a name the changed code uses),
found with `git grep -w -F` and ranked by mentions. Protected paths are never read.

**Formulas.**

- `id = sha1("\0".join(parts)).hexdigest()[:12]`: a file's parts are its path; a symbol's are path, qualified name and kind. Ids
  are stable across attempts, which is what `compare` and the web links rely on.
- `churnBucket = 0 if n <= 0 else min(5, 1 + int(log2(n)) // 2)`, with n = added + removed lines: 1 for 1-3 lines, 2 for 4-15,
  3 for 16-63, 4 for 64-255, 5 for 256 or more.
- `degree` = how many distinct symbols an edge connects it to.
- Hotspot: a changed symbol with `degree * (1 + churnBucket) >= 6`, at most the top `max(1, min(5, ceil(changes / 5)))` of them.
  A filtered view keeps the hotspots of the full graph.

**Layout** (`graphview.layout`, shared by the web page and the SVG export). A small layered layout: files are boxes 300 px wide,
users sit left of what they use, columns break at 2400 px. Same model in, same positions out; folding a file only shortens its box,
so nothing else moves sideways.

## Limits

- Edges are heuristics. Dynamic calls, reflection, dependency injection and a method called through a typed parameter
  (`def f(repo: OrderRepo): repo.orders_between()`) are found only when that method name is unique in the graph.
- Only the files of the diff and one hop of context are read: a caller three files away that never names the changed symbol is
  not there.
- A file's diff text is kept up to 3000 lines; files bigger than 1 MB are one row.
- The web page draws up to 600 symbols after filters; above that it shows the list and asks for a filter.

## Security and privacy

- **Nothing runs.** The analysed code is only read: `ast.parse` and regular expressions. No `eval`, no imports of the project,
  no subprocess besides git plumbing (`diff`, `cat-file`, `grep`, `merge-base`, `rev-parse`, `write-tree`, `log`), no network.
- **Paths.** Card ids and snapshot keys are checked against strict patterns (`SAFE_ID`, `<yyyymmdd-hhmmss>/<n>`) before they
  become part of a path under `.orchestrator/runs`. The analysed files are read from git objects, never from the working tree.
  Web query values are whitelisted or clamped (`orch/web_graph.py`).
- **Secrets.** Diff lines that match the guardrails' secret pattern are replaced with `[redacted: possible secret]` in the model,
  the reviewer findings get the same treatment, and a guardrail hit says where (`path:line`), never what.
- **Protected files** (the guardrails' `protected` list) show as a path with the note *protected file: content not shown*: no
  symbols, no diff, never used as context. The same model feeds every export (SVG, Mermaid, DOT, JSON), so exports follow the
  same filter.
- **Terminal and markup.** File and symbol names come from git and can hold anything: every string is stripped of control and
  bidi characters before it reaches a terminal or an SVG (printed JSON escapes every non-ASCII character), Mermaid and DOT
  labels are quoted, and the web page builds elements with `textContent`, never HTML from the server.

## Adding a language

One entry in `LANGS` in `orch/symbols.py`: the file extensions, its line-comment marks, its quote characters, whether `'`
can start a lifetime (Rust), its declaration patterns per scope (`top`, `ns`, `class`, `impl`) and, optionally, a pattern for base
classes. Each declaration pattern has a named group `name`, the kind it declares and the scope its body opens. Import parsing for
precise edges lives in `_imports` (same file); without it, edges fall back to unique names. Nothing else changes: the model, the
views and the web page are language-blind. Add an outline case to `tests/test_graph.py`; if the three-language golden model
should cover it too, add a file to its diff and run `UPDATE_GOLDEN=1 pytest tests/test_graph.py`, then read the golden diff.
