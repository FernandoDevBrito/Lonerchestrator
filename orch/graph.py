"""The change graph: a card's diff as the symbols it changed and the symbols that use them or are used by them.

    git diff -> files and hunks -> symbols (symbols.py) -> edges -> the model (versioned JSON) -> graphview.py draws it

Read-only: git plumbing (diff, cat-file, grep, merge-base, rev-parse), never a checkout, never the project's code, no network. The model is
built when a card's attempt reaches the guardrails (stages.py) and saved with the run's other artifacts; the web page and
`lonerchestrator graph` read it, or build one from the card's branch when there is none. Schema, formulas and how to add a language:
docs/change-graph.md."""
import bisect
import difflib
import hashlib
import json
import math
import re
import subprocess
import time
from fnmatch import fnmatch
from pathlib import Path

from . import symbols
from .gitops import Git
from .guardrails import SECRET, TEST_PATH

SCHEMA = 1
MAX_BYTES = 1_000_000              # a bigger file is one row
CONTEXT_FILES = 40                 # unchanged files read for callers and callees, the most mentions first
MAX_HUNK_LINES = 3000              # a file's diff text is kept in the model up to this many lines
TYPES = {"class", "interface", "enum", "type"}
HOT_SCORE = 6                      # hotspot: degree x (1 + churn bucket) at least this, the top fifth of the changes (1 to 5 of them)
IMPLICIT_THIS = {"csharp", "java", "kotlin", "swift"}               # a bare name may be a member of the enclosing class
PACKAGE_SCOPE = IMPLICIT_THIS | {"go", "php"}                       # a bare name may come from another file without an import
COMMON = {"get", "set", "add", "run", "call", "items", "keys", "values", "append", "extend", "update", "pop", "remove", "join", "split",
          "strip", "format", "read", "write", "open", "close", "copy", "clear", "find", "index", "count", "sort", "reverse", "insert",
          "replace", "lower", "upper", "encode", "decode", "map", "filter", "reduce", "forEach", "push", "slice", "splice", "then",
          "toString", "valueOf", "equals", "hashCode", "length", "size", "name", "type", "value", "data", "text", "path", "key", "next",
          "send", "emit", "log", "info", "warn", "error", "debug", "init", "main", "test", "setup", "start", "stop", "load", "save",
          "parse", "render", "apply", "bind", "has", "delete", "list", "dict", "str", "int", "len", "print", "range", "isinstance",
          "getattr", "setattr", "hasattr", "super", "object", "exists", "mkdir", "resolve", "match", "search", "group", "sub", "compile",
          "dumps", "loads", "dump", "result", "args", "kwargs", "self", "cls", "Add", "Get", "Set", "ToString", "Equals", "Dispose",
          "Invoke", "Length", "Count", "String", "Object", "Error", "Exception", "Promise", "Array", "Map", "List", "Dict", "Any"}
GENERATED = re.compile(r"@generated|DO NOT EDIT|auto-?generated", re.I)
LOCKFILE = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|composer\.lock|Gemfile\.lock|go\.sum)$|\.min\.(js|css)$")
SAFE_ID = re.compile(r"^[\w-][\w.-]{0,79}$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_ESC = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
REDACTED = "[redacted: possible secret]"


def _id(*parts):
    return hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:12]


def churn_bucket(n):
    """0 for no changed lines, then 1 block for 1-3 lines, 2 for 4-15, 3 for 16-63, 4 for 64-255, 5 for 256 or more."""
    return 0 if n <= 0 else min(5, 1 + int(math.log2(n)) // 2)


def specific(name):
    """A name rare enough to resolve by being the only one of its kind (common method names are not)."""
    return len(name) >= 3 and name not in COMMON and not name.startswith("__")


# ---------------------------------------------------------------- 1. the diff

def _unquote(s):
    """git's C-style quoted path ("a/x\\ty") -> text; an unquoted one is returned as it is."""
    if not s.startswith('"'):
        return s
    body, raw, i = s[1:-1] if len(s) > 1 and s.endswith('"') else s[1:], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body) and body[i + 1] in _ESC:
            raw.append(_ESC[body[i + 1]])
            i += 2
        elif c == "\\" and re.match(r"[0-7]{3}", body[i + 1:i + 4]):
            raw.append(int(body[i + 1:i + 4], 8))
            i += 4
        else:
            raw += c.encode("utf-8")
            i += 1
    return raw.decode("utf-8", "replace")


def _side(s, prefix):
    """The path on a ---/+++ line: None for /dev/null. git adds a tab after a name with spaces."""
    s = _unquote(s.rstrip("\t"))
    return None if s == "/dev/null" else s[len(prefix):] if s.startswith(prefix) else s


def _header_path(h):
    """The path in `diff --git a/X b/X` (only needed when nothing else names it: binary, empty or mode-only changes)."""
    if h.startswith('"'):
        end = next((i for i in range(1, len(h)) if h[i] == '"' and h[i - 1] != "\\"), len(h) - 1)
        return _side(h[end + 2:], "b/") or _side(h[:end + 1], "a/")
    n = (len(h) - 5) // 2
    if h.startswith("a/") and h[2 + n:] == " b/" + h[2:2 + n]:
        return h[2:2 + n]
    return h.split(" b/", 1)[-1]


def parse_diff(text):
    """Unified diff text -> one dict per file: path (the old path for a removed file), oldPath (renames), status
    (added | modified | removed | renamed), binary, blobs (old, new), hunks [{old, new, lines}], plus (new line numbers added)
    and minus (old line numbers removed)."""
    out, f, h, old_n, new_n = [], None, None, 0, 0
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            f = {"path": None, "oldPath": None, "status": "modified", "binary": False, "blobs": (None, None), "hunks": [], "plus": [], "minus": [],
                 "_h": line[11:]}
            out.append(f)
            h = None
            continue
        if f is None:
            continue
        if h is not None and line[:1] in (" ", "+", "-", "\\"):
            if line[0] == "+":
                f["plus"].append(new_n)
                new_n += 1
            elif line[0] == "-":
                f["minus"].append(old_n)
                old_n += 1
            elif line[0] == " ":
                old_n, new_n = old_n + 1, new_n + 1
            h["lines"].append(line)
            continue
        m = _HUNK.match(line)
        if m:
            old_n, new_n = int(m[1]), int(m[2])
            h = {"old": old_n, "new": new_n, "lines": []}
            f["hunks"].append(h)
            continue
        h = None
        if line.startswith("new file mode"):
            f["status"] = "added"
        elif line.startswith("deleted file mode"):
            f["status"] = "removed"
        elif line.startswith("rename from "):
            f["oldPath"], f["status"] = _unquote(line[12:]), "renamed"
        elif line.startswith("rename to "):
            f["path"] = _unquote(line[10:])
        elif line.startswith("index "):
            a, _, b = line[6:].split(" ")[0].partition("..")
            f["blobs"] = (None if set(a) <= {"0"} else a, None if set(b) <= {"0"} else b)
        elif line.startswith("--- "):
            f["_old"] = _side(line[4:], "a/")
        elif line.startswith("+++ "):
            f["_new"] = _side(line[4:], "b/")
        elif line.startswith("Binary files ") or line == "GIT binary patch":
            f["binary"] = True
    for f in out:
        hdr = _header_path(f.pop("_h"))
        old, new = f.pop("_old", hdr), f.pop("_new", hdr)
        f["path"] = f["path"] or (old if f["status"] == "removed" else new) or hdr
    return out


def _cat(git, names):
    """{object name: (text or None, note)}: blob ids or "rev:path" names, in two git calls. None = missing, binary, too big or generated."""
    names = list(dict.fromkeys(n for n in names if n and "\n" not in n))
    if not names:
        return {}

    def batch(mode, items):
        return subprocess.run(["git", *git.pre, "cat-file", mode], cwd=git.cwd, input=("\n".join(items) + "\n").encode("utf-8"),
                              capture_output=True, check=False).stdout
    out, small = {}, []
    for name, ln in zip(names, batch("--batch-check", names).decode("utf-8", "replace").split("\n"), strict=False):
        bits = ln.rsplit(" ", 2)
        if len(bits) != 3 or bits[1] != "blob":
            out[name] = (None, "not in git")
        elif int(bits[2]) > MAX_BYTES:
            out[name] = (None, "bigger than 1 MB: one row")
        else:
            small.append(name)
    data, pos = batch("--batch", small) if small else b"", 0
    for name in small:
        nl = data.index(b"\n", pos)
        size = int(data[pos:nl].split()[2])
        body = data[nl + 1:nl + 1 + size]
        pos = nl + 2 + size
        out[name] = (None, "binary: one row") if b"\0" in body[:8000] else (body.decode("utf-8", "replace"), "")
    return out


def _readable(path, text, note):
    """(text for the outline or None, note): generated, lock and minified files are one row."""
    if text is None:
        return None, note
    if LOCKFILE.search(path) or GENERATED.search("\n".join(text.split("\n", 6)[:6])):
        return None, "generated: one row"
    if symbols.lang_of(path) in ("javascript", "typescript") and max(map(len, text.split("\n")), default=0) > 1000:
        return None, "minified: one row"
    return text, ""


# ---------------------------------------------------------------- 2-3. symbols and how they use each other

class World:
    """Every known file of one version (before or after the change): its symbols, what its lines use, and how a used name resolves."""

    def __init__(self):
        self.files = {}           # key -> {"real", "lang", "syms" (row 0 = module level), "quals", "owner", "uses", "bases", "note", "text"}
        self.top, self.members, self.stems = {}, {}, {}
        self._bound = {}

    def add(self, key, real, text, note=""):
        syms, uses, why = symbols.parse(real, text) if text is not None else ([], [], "")
        n = text.count("\n") + 1 if text is not None else 0
        mod = {"name": "Module level", "kind": "module", "start": 1, "end": max(n, 1), "qual": "", "parent": None}
        rows = [mod, *syms]
        owner = [0] * (n + 2) if text is not None else None
        if owner is not None:
            for i in sorted(range(1, len(rows)), key=lambda i: (rows[i]["start"], -rows[i]["end"])):
                for ln in range(rows[i]["start"], min(rows[i]["end"], n) + 1):
                    owner[ln] = i
        quals = {s["qual"]: s for s in syms}
        bases = {}
        for ln, name, role, _ in uses:
            if role == "base" and owner is not None:
                bases.setdefault(rows[owner[ln]]["qual"], []).append(name)
        self.files[key] = {"real": real, "lang": symbols.lang_of(real), "syms": rows, "quals": quals, "owner": owner, "uses": uses,
                           "bases": bases, "note": note or why, "text": text}
        for s in syms:
            (self.top if s["parent"] is None else self.members).setdefault(s["name"], []).append((key, s))
        stem = real.rsplit(".", 1)[0] if "." in real.rsplit("/", 1)[-1] else real
        self.stems.setdefault(stem.rsplit("/", 1)[-1], []).append((stem, key))

    # ---- resolving a name
    def _modules(self, key, mod):
        """The files a module reference may mean: relative to the importing file ("./x", ".x", "..x"), or a dotted or slashed path."""
        real = self.files[key]["real"]
        here = real.rsplit("/", 1)[0].split("/") if "/" in real else []
        if mod.startswith(".") and ("/" in mod):                                  # JS: ./x, ../x
            parts = list(here)
            for seg in mod.split("/"):
                parts = parts[:-1] if seg == ".." else parts if seg in (".", "") else [*parts, seg]
            want, exact = "/".join(parts), True
        elif mod.startswith("."):                                                 # Python: .x, ..x.y, .
            level = len(mod) - len(mod.lstrip("."))
            rest = mod.lstrip(".")
            parts = here[:len(here) - (level - 1)] if level > 1 else list(here)
            want, exact = "/".join(parts + (rest.split(".") if rest else [])), True
        else:
            want = re.sub(r"^(crate|self|super)::", "", mod).replace("::", "/").replace("\\", "/").replace(".", "/").strip("/")
            exact = False
        found = []
        for tail in (want, f"{want}/__init__", f"{want}/index", f"{want}/mod"):
            last = tail.rsplit("/", 1)[-1]
            for stem, k in self.stems.get(last, ()):
                if stem == tail or (not exact and stem.endswith("/" + tail)):
                    found.append(k)
            if found:
                break
        return found

    def bound(self, key):
        """{local name: (file key, symbol)} for the imports of a file; the symbol is the module row when a whole module was imported."""
        if key not in self._bound:
            got = {}
            for _, local, role, via in self.files[key]["uses"]:
                if role != "import":
                    continue
                mod, _, name = via.rpartition(":")
                t = None
                files = self._modules(key, mod)
                if name:
                    t = next(((k, self.files[k]["quals"][name]) for k in files if name in self.files[k]["quals"]), None)
                    if t is None and self.files[key]["lang"] == "python":         # from pkg import module
                        sub = self._modules(key, (mod + name) if mod.endswith(".") else f"{mod}.{name}")
                        t = (sub[0], self.files[sub[0]]["syms"][0]) if sub else None
                elif files:
                    t = (files[0], self.files[files[0]]["syms"][0])
                if t:
                    got[local] = t
            self._bound[key] = got
        return self._bound[key]

    def _cls(self, key, sym):
        quals = self.files[key]["quals"]
        while sym is not None and sym["kind"] not in TYPES:
            sym = quals.get(sym["parent"]) if sym["parent"] else None
        return sym

    def _member(self, key, cls, name, seen=0):
        """A member of a class, or of one of its bases (by name, when only one class has that name)."""
        s = self.files[key]["quals"].get(f"{cls['qual']}.{name}")
        if s:
            return key, s
        for b in self.files[key]["bases"].get(cls["qual"], ()) if seen < 3 else ():
            t = self.bound(key).get(b) or self._only(self.top, b)
            if t and t[1]["kind"] in TYPES:
                hit = self._member(t[0], t[1], name, seen + 1)
                if hit:
                    return hit
        return None

    def _only(self, index, name):
        found = index.get(name, ())
        return found[0] if len(found) == 1 else None

    def resolve(self, key, own, name, role, via):
        """(file key, symbol) that a use means, or None. Precise first (imports, this file, this class), then a guess only for a
        name that exactly one symbol has."""
        f = self.files[key]
        imports = self.bound(key)
        if role == "import":
            return imports.get(name)
        if via == "":
            t = imports.get(name)
            if t:
                return (t[0], self.files[t[0]]["quals"][name]) if t[1]["kind"] == "module" and name in self.files[t[0]]["quals"] else t
            s = f["quals"].get(name)
            if s is not None and s["parent"] is None:
                return key, s
            if f["lang"] in IMPLICIT_THIS:
                cls = self._cls(key, own)
                hit = cls and self._member(key, cls, name)
                if hit:
                    return hit
            return self._only(self.top, name) if f["lang"] in PACKAGE_SCOPE and specific(name) else None
        if via == "self":
            cls = self._cls(key, own)
            return self._member(key, cls, name) if cls else None
        if via != ".":
            t = imports.get(via)
            if t and t[1]["kind"] == "module":
                s = self.files[t[0]]["quals"].get(name)
                return (t[0], s) if s is not None and s["parent"] is None else None
            if t and t[1]["kind"] in TYPES:
                return self._member(t[0], t[1], name)
            s = f["quals"].get(via)
            if s is not None and s["kind"] in TYPES:
                return self._member(key, s, name)
        return self._only(self.members, name) if specific(name) else None

    def edges(self):
        """{((key, qual, kind) user, (key, qual, kind) used, edge kind): weight} for every use that resolves."""
        out = {}
        for key, f in self.files.items():
            test = bool(TEST_PATH.search(f["real"]))
            rows, owner = f["syms"], f["owner"]
            for ln, name, role, via in f["uses"]:
                own = rows[0] if role == "import" or owner is None or ln >= len(owner) else rows[owner[ln]]
                t = self.resolve(key, own, name, role, via)
                if t is None or (t[0] == key and t[1] is own):
                    continue
                kind = _edge_kind(role, t[1]["kind"], test)
                e = ((key, own["qual"], own["kind"]), (t[0], t[1]["qual"], t[1]["kind"]), kind)
                out[e] = out.get(e, 0) + 1
        return out


def _edge_kind(role, target, test):
    if role == "import":
        return "imports"
    if role == "base":
        return "implements" if target == "interface" else "extends"
    if role == "store":
        return "writes"
    if target in TYPES and role != "call":
        kind = "typeref"
    elif role == "call" or target in ("function", "method"):
        kind = "calls"
    else:
        kind = "reads"
    return "tests" if test and kind in ("calls", "reads") else kind


# ---------------------------------------------------------------- 4. the model

def _count(lines, s):
    return bisect.bisect_right(lines, s["end"]) - bisect.bisect_left(lines, s["start"])


def _own_count(lines, owner, idx):
    """Changed lines that belong to the module level itself (not to any symbol)."""
    return sum(1 for ln in lines if owner is None or ln >= len(owner) or owner[ln] == idx)


def _body(text, s):
    return [ln.strip() for ln in text.split("\n")[s["start"] - 1:s["end"]]] if text is not None else []


def _rows(f, old, new):
    """The symbols of one changed file: {(qual, kind): row} with status added | removed | modified | context and changed lines."""
    plus, minus = sorted(f["plus"]), sorted(f["minus"])
    olds = {(s["qual"], s["kind"]): s for s in old["syms"]} if old else {}
    news = {(s["qual"], s["kind"]): s for s in new["syms"]} if new else {}
    rows = {}
    for k in sorted(set(olds) | set(news)):
        ns, os_ = news.get(k), olds.get(k)
        if k[1] == "module":
            a = _own_count(plus, new and new["owner"], 0) if ns else 0
            r = _own_count(minus, old and old["owner"], 0) if os_ else 0
        else:
            a, r = (_count(plus, ns) if ns else 0), (_count(minus, os_) if os_ else 0)
        if k[1] == "module":                                                    # the module row counts only its own lines
            status = ({"added": "added", "removed": "removed"}.get(f["status"], "modified")) if a or r else "context"
        else:
            status = ("modified" if a or r else "context") if ns and os_ else "added" if ns else "removed"
        row = {"sym": ns or os_, "status": status, "added": a, "removed": r, "side": "new" if ns else "old"}
        if status == "modified" and k[1] != "module" and _body(old["text"], os_) == _body(new["text"], ns):
            row["moved"] = True
        rows[k] = row
    if rows and all(r["status"] == "context" for r in rows.values()):       # binary, empty, renamed or mode-only: the file still shows
        rows[("", "module")]["status"] = {"added": "added", "removed": "removed"}.get(f["status"], "modified")
    return rows


def _renames(changed, old_world, new_world):
    """Removed + added symbols with nearly the same body (difflib ratio >= 0.8, same kind) are one renamed or moved symbol.
    Returns {old (key, qual, kind): new (key, qual, kind)} and folds each pair into one row."""
    gone = [(fk, k, r) for fk, rows in changed.items() for k, r in rows.items() if r["status"] == "removed" and k[1] != "module"]
    born = [(fk, k, r) for fk, rows in changed.items() for k, r in rows.items() if r["status"] == "added" and k[1] != "module"]
    pairs = []
    for ofk, ok, orow in gone[:300]:
        a = _body(old_world.files[ofk]["text"], orow["sym"]) if ofk in old_world.files else []
        for nfk, nk, nrow in born[:300]:
            if nk[1] != ok[1] or not a:
                continue
            b = _body(new_world.files[nfk]["text"], nrow["sym"])
            if not b or not 0.5 <= len(a) / len(b) <= 2:
                continue
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            if sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.8:
                pairs.append((sm.ratio(), ofk, ok, nfk, nk))
    out, used = {}, set()
    for _, ofk, ok, nfk, nk in sorted(pairs, key=lambda p: (-p[0], p[1], p[2], p[3], p[4])):
        if (ofk, ok) in used or (nfk, nk) in used:
            continue
        used |= {(ofk, ok), (nfk, nk)}
        orow, nrow = changed[ofk].pop(ok), changed[nfk][nk]
        nrow.update(status="modified", removed=orow["removed"], **{"from": {"path": ofk, "qual": ok[0]}})
        out[(ofk, ok[0], ok[1])] = (nfk, nk[0], nk[1])
    return out


def _grep(git, names, rev):
    """{path: lines mentioning any of the names} over the files the graph can read (rev "" = the index)."""
    if not names:
        return {}
    exts = sorted({e for exts in symbols.LANGS for e in exts} | set(symbols.PYTHON))
    args = ["grep", "-c", "-z", "-I", "-w", "-F", *[a for n in names for a in ("-e", n)], *(["--cached"] if not rev else [rev]), "--",
            *[f"*{e}" for e in exts]]
    r = git.run(*args, check=False)
    out = {}
    for ln in r.stdout.split("\n"):
        path, _, n = ln.partition("\0")
        if n.strip().isdigit():
            out[path[len(rev) + 1:] if rev and path.startswith(rev + ":") else path] = int(n)
    return out


def _secret_lines(f):
    """New line numbers of added lines that look like a secret (the guardrails' own pattern)."""
    hits = []
    for h in f["hunks"]:
        n = h["new"]
        for ln in h["lines"]:
            if ln[:1] == "+" and SECRET.search(ln):
                hits.append(n)
            n += 1 if ln[:1] in ("+", " ") else 0
    return hits


def _redact(lines):
    return [f"{ln[0]}{REDACTED}" if ln[:1] in ("+", "-", " ") and SECRET.search(ln) else ln for ln in lines]


def build(project, base, head=None, *, staged=False, card="", attempt=0, guard=None, source=""):
    """The model of one change: `base` against the index (staged=True, what the pipeline just staged) or against commit `head`
    (from where the two histories meet). `guard` is the guardrails config (protected paths, limits); see docs/change-graph.md."""
    git = Git(project)
    guard = guard or {}
    old_rev = git.out("rev-parse", "--verify", f"{base}^{{commit}}").strip()
    if staged:
        spec, new_rev = ["--cached", old_rev], git.run("write-tree", check=False).stdout.strip()
    else:
        head = git.out("rev-parse", "--verify", f"{head}^{{commit}}").strip()
        old_rev = git.out("merge-base", old_rev, head).strip()
        spec, new_rev = [old_rev, head], head
    text = git.out("-c", "core.quotePath=false", "diff", "-M", "--full-index", "-U3", "--no-color", "--no-ext-diff", "--no-textconv",
                   "--no-relative", "--src-prefix=a/", "--dst-prefix=b/", *spec, "--")
    files = parse_diff(text)

    def name(rev, path):
        return f":{path}" if rev == ":" else f"{rev}:{path}"
    new_side = ":" if staged else new_rev
    want = {}
    for f in files:
        o, n = f["blobs"]
        same = not o and not n and f["status"] in ("renamed", "modified")
        f["_o"] = None if f["status"] == "added" else o or name(old_rev, f["oldPath"] or f["path"])
        f["_n"] = None if f["status"] == "removed" else (f["_o"] if same else n or name(new_side, f["path"]))
        want.update({f["_o"]: f["oldPath"] or f["path"], f["_n"]: f["path"]})
    got = _cat(git, [k for k in want if k])
    protected = guard.get("protected", [])

    def is_protected(f):
        return any(fnmatch(p, pat) for p in filter(None, (f["path"], f["oldPath"])) for pat in protected)
    old_w, new_w = World(), World()
    for f in files:
        f["protected"] = is_protected(f)
        for side, w, real in (("_o", old_w, f["oldPath"] or f["path"]), ("_n", new_w, f["path"])):
            if f[side] is None:
                continue
            txt, note = got.get(f[side], (None, "not in git"))
            txt, note = (None, "protected file: content not shown") if f["protected"] else (None, "binary: one row") if f["binary"] else _readable(real, txt, note)
            if txt is None and not note and not symbols.lang_of(real):
                note = "no outline for this language: the file is one row"
            w.add(f["path"], real, txt, note)
    changed = {f["path"]: _rows(f, old_w.files.get(f["path"]), new_w.files.get(f["path"])) for f in files}
    renamed = _renames(changed, old_w, new_w)

    # one hop of context: unchanged files that mention a changed name, or a name the changed code uses
    names = {r["sym"]["name"] for rows in changed.values() for r in rows.values() if r["status"] != "context" and r["sym"]["kind"] != "module"}
    for f in files:
        w = new_w.files.get(f["path"])
        if w and w["owner"] is not None:
            plus = set(f["plus"])
            names |= {u[1] for u in w["uses"] if u[0] in plus and u[2] != "import"}
    diff_paths = {f["path"] for f in files} | {f["oldPath"] for f in files if f["oldPath"]}
    hits = _grep(git, sorted(n for n in names if specific(n))[:300], "" if staged else new_rev)
    ctx = sorted((p for p in hits if p not in diff_paths and not any(fnmatch(p, pat) for pat in protected)), key=lambda p: (-hits[p], p))[:CONTEXT_FILES]
    ctx_got = _cat(git, [name(new_side, p) for p in ctx])
    for p in ctx:
        txt, note = _readable(p, *ctx_got.get(name(new_side, p), (None, "")))
        if txt is not None:
            old_w.add(p, p, txt, note)
            new_w.add(p, p, txt, note)

    # edges of both versions; an edge is drawn when at least one end changed, and says if the change added or removed it
    def norm(end):
        return renamed.get(end, end)
    now = new_w.edges()
    before = {}
    for (a, b, k), wgt in old_w.edges().items():
        e = (norm(a), norm(b), k)
        before[e] = before.get(e, 0) + wgt
    status_of = {(fk, k[0], k[1]): r["status"] for fk, rows in changed.items() for k, r in rows.items()}

    def moved(end):
        return status_of.get(end, "context") != "context"
    edges = []
    for e in sorted(set(now) | set(before)):
        a, b, kind = e
        if a == b or not (moved(a) or (moved(b) and kind != "imports")) or (kind == "imports" and e in now and e in before):
            continue                                                          # an import the change did not touch is noise
        edges.append({"from": _id(*a), "to": _id(*b), "kind": kind, "weight": now.get(e) or before.get(e),
                      "status": "kept" if e in now and e in before else "added" if e in now else "removed", "_ends": (a, b)})

    # the rows to show: every changed symbol, every end of a drawn edge, and their parents (so the tree reads right)
    show = {(fk, k[0], k[1]) for fk, rows in changed.items() for k, r in rows.items() if r["status"] != "context"}
    show |= {end for e in edges for end in e["_ends"]}
    worlds = (new_w, old_w)

    def sym_of(end):
        fk, qual, kind = end
        for w in worlds:
            f = w.files.get(fk)
            if f is not None:
                s = f["syms"][0] if kind == "module" else f["quals"].get(qual)
                if s is not None and s["kind"] == kind:
                    return s
        return None
    for end in sorted(show):
        s = sym_of(end)
        while s is not None and s["parent"]:
            fk = end[0]
            parent = next((w.files[fk]["quals"][s["parent"]] for w in worlds if fk in w.files and s["parent"] in w.files[fk]["quals"]), None)
            if parent is None:
                break
            show.add((fk, parent["qual"], parent["kind"]))
            s = parent

    by_file = {}
    for end in show:
        by_file.setdefault(end[0], []).append(end)
    secrets = {f["path"]: _secret_lines(f) for f in files if not f["protected"]}
    out_files = []
    fmeta = {f["path"]: f for f in files}
    for fk in sorted(by_file):
        f = fmeta.get(fk)
        w = new_w.files.get(fk) or old_w.files.get(fk)
        rows = changed.get(fk, {})
        ids = {end[1]: _id(*end) for end in by_file[fk] if end[2] != "module"}
        syms = []
        for end in by_file[fk]:
            row = rows.get((end[1], end[2]))
            s = row["sym"] if row else sym_of(end)
            if s is None:
                continue
            st = row["status"] if row else "context"
            a, r = (row["added"], row["removed"]) if row else (0, 0)
            item = {"id": _id(*end), "name": s["name"], "qual": s["qual"], "kind": s["kind"], "parent": ids.get(s["parent"]) if s["parent"] else None,
                    "status": st, "added": a, "removed": r, "churnBucket": churn_bucket(a + r),
                    "range": {"start": s["start"], "end": s["end"], **({"side": "old"} if row and row["side"] == "old" else {})},
                    "findings": [], "guardrails": []}
            if row and row.get("from"):
                item["from"] = row["from"]
            if row and row.get("moved"):
                item["moved"] = True
            syms.append(item)
        syms.sort(key=lambda s: (s["kind"] != "module", s["range"]["start"], s["qual"], s["kind"]))
        entry = {"id": _id(fk), "path": fk, "oldPath": f["oldPath"] if f else None, "lang": (w or {}).get("lang", "") or "",
                 "status": f["status"] if f else "context", "added": len(f["plus"]) if f else 0, "removed": len(f["minus"]) if f else 0,
                 "note": (w or {}).get("note", ""), "guardrails": [], "hunks": [], "symbols": syms}
        if f and not f["protected"]:
            size = sum(len(h["lines"]) for h in f["hunks"])
            if size <= MAX_HUNK_LINES:
                entry["hunks"] = [{"old": h["old"], "new": h["new"], "lines": _redact(h["lines"])} for h in f["hunks"]]
            else:
                entry["note"] = (entry["note"] + "; " if entry["note"] else "") + f"diff of {size} lines not kept"
        out_files.append(entry)

    # guardrails, anchored where they happen (same rules as guardrails.py; this only shows them)
    notes = []
    by_path = {e["path"]: e for e in out_files}
    for f in files:
        e = by_path.get(f["path"])
        if e is None:
            continue
        if f["protected"]:
            e["guardrails"].append("protected path modified")
        if f["status"] == "removed" and guard.get("forbid_test_deletion", True) and TEST_PATH.search(f["path"]):
            e["guardrails"].append("test file deleted")
        if guard.get("scan_secrets", True):
            for ln in secrets.get(f["path"], ()):
                owner = _owner_row(e["symbols"], ln)
                (owner["guardrails"] if owner else e["guardrails"]).append(f"possible secret in added line {ln}")
    n_paths = sum(2 if f["status"] == "renamed" else 1 for f in files)
    n_lines = sum(len(f["plus"]) + len(f["minus"]) for f in files)
    if guard.get("max_files") and n_paths > guard["max_files"]:
        notes.append(f"{n_paths} files changed, limit {guard['max_files']}")
    if guard.get("max_diff_lines") and n_lines > guard["max_diff_lines"]:
        notes.append(f"{n_lines} changed lines, limit {guard['max_diff_lines']}")

    for e in edges:
        del e["_ends"]
    model = {"schemaVersion": SCHEMA,
             "snapshot": {"cardId": card, "attempt": attempt, "base": old_rev, "head": new_rev, "source": source or ("staged" if staged else "commit"),
                          "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S")},
             "stats": {}, "files": out_files, "edges": edges, "groups": [], "guardrails": notes, "findings": []}
    _finish(model)
    return model


def _owner_row(syms, ln):
    """The innermost shown symbol of the new version whose range holds a line."""
    best = None
    for s in syms:
        r = s["range"]
        if r.get("side") != "old" and s["kind"] != "module" and r["start"] <= ln <= r["end"] and (best is None or r["start"] >= best["range"]["start"]):
            best = s
    return best or next((s for s in syms if s["kind"] == "module"), None)


def _finish(model, rank=True):
    """Degree, hotspots, groups and stats: everything derived from files and edges. A filtered view keeps the full graph's hotspots."""
    syms = {s["id"]: s for f in model["files"] for s in f["symbols"]}
    if rank:
        nbrs = {}
        for e in model["edges"]:
            if e["from"] in syms and e["to"] in syms:
                nbrs.setdefault(e["from"], set()).add(e["to"])
                nbrs.setdefault(e["to"], set()).add(e["from"])
        for s in syms.values():
            s["degree"] = len(nbrs.get(s["id"], ()))
            s.pop("hotspot", None)
        changed = sum(1 for s in syms.values() if s["status"] != "context")
        for s in sorted((s for s in syms.values() if s["status"] != "context" and s["degree"] * (1 + s["churnBucket"]) >= HOT_SCORE),
                        key=lambda s: (-s["degree"] * (1 + s["churnBucket"]), s["id"]))[:max(1, min(5, math.ceil(changed / 5)))]:
            s["hotspot"] = True
    ranked = [s for s in syms.values() if s.get("hotspot")]
    groups = {}
    for f in model["files"]:
        groups.setdefault(f["path"].rsplit("/", 1)[0] if "/" in f["path"] else ".", []).append(f["id"])
    model["groups"] = [{"id": _id("group", g), "label": g, "fileIds": ids} for g, ids in sorted(groups.items())]
    changed = [s for s in syms.values() if s["status"] != "context"]
    model["stats"] = {"files": len(model["files"]), "symbols": len(syms), "changes": len(changed),
                      "added": sum(f["added"] for f in model["files"]), "removed": sum(f["removed"] for f in model["files"]),
                      "edges": len(model["edges"]), "hotspots": len(ranked),
                      "findings": sum(len(s["findings"]) for s in syms.values()) + len(model.get("findings", [])),
                      "guardrails": sum(len(s["guardrails"]) for s in syms.values()) + sum(len(f["guardrails"]) for f in model["files"]) + len(model.get("guardrails", []))}
    return model


def dumps(model):
    """Deterministic JSON text: the same change always gives the same bytes (only snapshot.createdAt says when)."""
    return json.dumps(model, ensure_ascii=False, separators=(",", ":"))


def summary_line(model):
    """One line for the card's log: `Graph: 4 files, 23 symbols, 12 changes, 1 hotspot, 0 findings`."""
    st = model["stats"]
    return "Graph: " + ", ".join(f"{st[k]} {w if st[k] == 1 else w + 's'}" for k, w in
                                 (("files", "file"), ("symbols", "symbol"), ("changes", "change"), ("hotspots", "hotspot"), ("findings", "finding")))


def label(model):
    """{symbol id: "path:line qual"} for text output."""
    return {s["id"]: f"{f['path']}:{s['range']['start']} {s['qual'] or 'module level'}" for f in model["files"] for s in f["symbols"]}


def review_text(model, limit=12):
    """The graph in a few lines for a reviewer: hotspots, dependencies the change adds or removes, edges between directories, guardrail hits.
    Derived only from the diff (never from the builder's own words), so it keeps the rule that whoever builds never evaluates."""
    name = label(model)
    syms = {s["id"]: (f, s) for f in model["files"] for s in f["symbols"]}
    out = [summary_line(model)]
    hot = sorted((s for _, s in syms.values() if s.get("hotspot")), key=lambda s: (-s["degree"], s["id"]))
    if hot:
        out += ["Hotspots (most connected changed symbols):"] + [f"- {name[s['id']]} ({s['status']}, {s['degree']} neighbours, +{s['added']} -{s['removed']})" for s in hot]
    for st, title in (("added", "Dependencies this change adds:"), ("removed", "Dependencies this change removes:")):
        es = [e for e in model["edges"] if e["status"] == st]
        if es:
            out += [title] + [f"- {name[e['from']]} {e['kind']} {name[e['to']]}" for e in es[:limit]] + ([f"- ... {len(es) - limit} more"] if len(es) > limit else [])
    cross = [e for e in model["edges"] if e["status"] != "removed" and syms[e["from"]][0]["path"].split("/")[0] != syms[e["to"]][0]["path"].split("/")[0]]
    if cross:
        out += ["Edges between top-level directories:"] + [f"- {name[e['from']]} {e['kind']} {name[e['to']]}" for e in cross[:limit]]
    hits = [f"- {f['path']}: {g}" for f in model["files"] for g in f["guardrails"]] + [f"- {name[s['id']]}: {g}" for f, s in syms.values() for g in s["guardrails"]]
    if hits or model.get("guardrails"):
        out += ["Guardrail hits:"] + hits + [f"- {g}" for g in model.get("guardrails", [])]
    return "\n".join(out)


# ---------------------------------------------------------------- 5. reading: saved snapshots, reviewers' findings, filters

def _runs(project):
    return Path(project) / ".orchestrator" / "runs"


def snapshots(project, cid):
    """Every model the pipeline saved for a card, oldest first: [{"key": "<run>/<attempt>", "run", "attempt"}]."""
    if not SAFE_ID.match(cid or ""):
        return []
    found = []
    for p in _runs(project).glob(f"*/{cid}/graph*.json"):
        if p.stem[5:].isdigit():
            found.append({"key": f"{p.parent.parent.name}/{int(p.stem[5:])}", "run": p.parent.parent.name, "attempt": int(p.stem[5:])})
    return sorted(found, key=lambda s: (s["run"], s["attempt"]))


_FAIL = re.compile(r"^[#*\s]*FAILURES[:*\s]*$(.*?)(?=^[#*\s]*VERDICT|\Z)", re.M | re.S)       # also "FAILURES:" and "**FAILURES**"
_REF = re.compile(r"([\w.@/-]+\.[A-Za-z0-9]+)(?::(\d+))?")


def failures(text):
    """The bullet lines under FAILURES in a reviewer's output (the qa and GEMINI.md format), without "none"."""
    m = _FAIL.search(text or "")
    items = [ln.strip()[2:].strip() for ln in (m.group(1) if m else "").splitlines() if ln.strip().startswith("- ")]
    return [i for i in items if i.strip("() .").lower() not in ("none", "")]


def add_findings(model, reviews):
    """Lay each reviewer's FAILURES on the symbol a `path:line` in it points at, on the file a bare path names, or on the graph."""
    from .agents import verdict
    files = {f["path"]: f for f in model["files"]}
    for who, text in sorted(reviews.items()):
        sev = "blocking" if verdict(text) == "REJECTED" else "note"
        for item in failures(text):
            item = SECRET.sub(REDACTED, item)[:400]
            spot, line = None, None
            for path, ln in _REF.findall(item):
                f = files.get(path.removeprefix("./")) or next((f for p, f in files.items() if p.endswith("/" + path)), None)
                if f is not None:
                    line = int(ln) if ln else None
                    spot = _owner_row(f["symbols"], line) if line else next((s for s in f["symbols"] if s["kind"] == "module"), None)
                    if spot is not None:
                        break
            got = {"reviewer": who, "severity": sev, "text": item, **({"line": line} if line else {})}
            (spot["findings"] if spot is not None else model.setdefault("findings", [])).append(got)
    return _finish(model, rank=False)


def read(project, cid, key):
    """One saved model, with the findings of the reviews of that same attempt. None when it is not there."""
    run, _, n = (key or "").partition("/")
    if not (SAFE_ID.match(cid or "") and re.match(r"^\d{8}-\d{6}$", run) and n.isdigit()):
        return None
    d = _runs(project) / run / cid
    try:
        model = json.loads((d / f"graph{n}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    reviews = {p.stem[len(f"review{n}-"):]: p.read_text(encoding="utf-8", errors="replace") for p in sorted(d.glob(f"review{n}-*.txt"))}
    return add_findings(model, reviews) if reviews else model


_CACHE = {}


def from_git(project, cid, base, guard=None):
    """A model straight from git when the pipeline saved none: the card's branch, else the merge that brought it into base. None if neither."""
    if not SAFE_ID.match(cid or ""):
        return None
    git = Git(project)
    br = f"card/{cid}"
    if git.has_branch(br):
        start, head, src = base, br, "branch"
    else:
        sha = git.run("log", base, "--merges", "-1", "--format=%H", "--fixed-strings", f"--grep=Merge card {cid}:", check=False).stdout.strip()
        if not sha:
            return None
        start, head, src = f"{sha}^1", f"{sha}^2", "merge"
    key = (str(project), cid, git.run("rev-parse", start, head, check=False).stdout, json.dumps(guard, sort_keys=True))
    if key not in _CACHE:
        if len(_CACHE) > 32:
            _CACHE.clear()
        _CACHE[key] = dumps(build(project, start, head, card=cid, guard=guard, source=src))
    return json.loads(_CACHE[key])


def load(project, cid, base, guard=None, key=None):
    """(model, snapshots) for a card: the saved attempt `key` (default: the latest), else one built from git. model is None when the card
    has no change to show yet."""
    snaps = snapshots(project, cid)
    if key and key not in {s["key"] for s in snaps}:
        return None, snaps
    if snaps:
        return read(project, cid, key or snaps[-1]["key"]), snaps
    return from_git(project, cid, base, guard), snaps


def view(model, only=(), hide=(), findings=False, guardrails=False, focus="", depth=1, query=""):
    """A filtered copy. only: statuses to keep; hide: "context" and/or "tests"; findings / guardrails: only symbols that have some;
    focus: a symbol (id, name or qualified name) or a file (path or id) and everything `depth` edges away; query: part of a name or path.
    Parents of what stays also stay, so the tree still reads."""
    m = json.loads(dumps(model))
    syms = {s["id"]: (f, s) for f in m["files"] for s in f["symbols"]}
    keep = set(syms)
    if only:
        keep = {i for i in keep if syms[i][1]["status"] in only}
    if "context" in hide:
        keep = {i for i in keep if syms[i][1]["status"] != "context"}
    if "tests" in hide:
        keep = {i for i in keep if not TEST_PATH.search(syms[i][0]["path"])}
    if findings:
        keep = {i for i in keep if syms[i][1]["findings"]}
    if guardrails:
        keep = {i for i in keep if syms[i][1]["guardrails"] or (syms[i][1]["kind"] == "module" and syms[i][0]["guardrails"])}
    if query:
        q = query.lower()
        keep = {i for i in keep if q in syms[i][1]["qual"].lower() or q in syms[i][0]["path"].lower()}
    if focus:
        seen = {i for i, (f, s) in syms.items() if focus in (i, s["name"], s["qual"], f["path"], f["id"])}
        adj = {}
        for e in m["edges"]:
            adj.setdefault(e["from"], set()).add(e["to"])
            adj.setdefault(e["to"], set()).add(e["from"])
        edge = set(seen)
        for _ in range(max(0, depth)):
            edge = {n for i in edge for n in adj.get(i, ())} - seen
            seen |= edge
        keep &= seen
    for i in list(keep):
        p = syms[i][1]["parent"]
        while p and p in syms and p not in keep:
            keep.add(p)
            p = syms[p][1]["parent"]
    for f in m["files"]:
        f["symbols"] = [s for s in f["symbols"] if s["id"] in keep]
    m["files"] = [f for f in m["files"] if f["symbols"]]
    m["edges"] = [e for e in m["edges"] if e["from"] in keep and e["to"] in keep]
    return _finish(m, rank=False)


def compare(old, new):
    """What the fix loop changed between two attempts: `new` with a `delta` on every symbol and edge, "new" (not in `old`),
    "changed" (in both, different lines or status), "same", or "gone" (only in `old`; put back so it shows)."""
    m = json.loads(dumps(new))
    before = {s["id"]: (f, s) for f in old["files"] for s in f["symbols"]}
    files = {f["id"]: f for f in m["files"]}
    for f in m["files"]:
        for s in f["symbols"]:
            o = before.get(s["id"])
            s["delta"] = "new" if o is None else "same" if (o[1]["status"], o[1]["added"], o[1]["removed"]) == (s["status"], s["added"], s["removed"]) else "changed"
    have = {s["id"] for f in m["files"] for s in f["symbols"]}
    for sid, (f, s) in sorted(before.items(), key=lambda t: (t[1][0]["path"], t[1][1]["range"]["start"])):
        if sid not in have:
            if f["id"] not in files:
                files[f["id"]] = {**json.loads(dumps(f)), "symbols": [], "hunks": []}
                m["files"].append(files[f["id"]])
            files[f["id"]]["symbols"].append({**json.loads(dumps(s)), "delta": "gone", "findings": []})
    now = {(e["from"], e["to"], e["kind"]) for e in m["edges"]}
    was = {(e["from"], e["to"], e["kind"]): e for e in old["edges"]}
    for e in m["edges"]:
        e["delta"] = "same" if (e["from"], e["to"], e["kind"]) in was else "new"
    m["edges"] += [{**e, "delta": "gone"} for k, e in sorted(was.items()) if k not in now]
    m["files"].sort(key=lambda f: f["path"])
    m["compare"] = {"from": old.get("snapshot", {}), "to": new.get("snapshot", {})}
    return _finish(m, rank=False)


def lines_of(model, sid):
    """The diff lines inside one symbol's range, as (old line or None, new line or None, text): what the side panel and Enter in
    `lonerchestrator graph --tui` show. A removed symbol is matched on the old side, every other one on the new side."""
    for f in model["files"]:
        s = next((s for s in f["symbols"] if s["id"] == sid), None)
        if s is None:
            continue
        old_side, a, b = s["range"].get("side") == "old", s["range"]["start"], s["range"]["end"]
        out = []
        for h in f["hunks"]:
            o, n = h["old"], h["new"]
            for ln in h["lines"]:
                tag = ln[:1]
                if tag == "\\":
                    continue
                at = o if old_side else n
                if a <= at <= b or s["kind"] == "module":
                    out.append((o if tag != "+" else None, n if tag != "-" else None, ln))
                o += tag != "+"
                n += tag != "-"
        return out
    return []
