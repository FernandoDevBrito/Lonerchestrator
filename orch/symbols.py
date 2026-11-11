"""Symbols of one source file, for the change graph: what is declared where (name, kind, line range) and what each line uses.

Python is parsed exactly by the standard library (`ast`; the code is only read, never run). The other languages get an outline from
declaration patterns plus brace matching: good enough to put a changed line inside the right function or class, not a compiler.
A language this file does not know, or a file that cannot be read, becomes one "Module level" row (graph.py), so nothing ever breaks.

    parse(path, text) -> (symbols, uses, note)
        symbols  [{"name", "kind", "start", "end", "qual", "parent"}]   lines are 1-based and inclusive; parent is the parent's qual
        uses     [(line, name, role, via)]
                 role: call | load | store | annot | base | import
                 via:  how the name was reached. "" = a bare name, "self" = self/this/cls, "<name>" = an attribute of that name
                       (`graph.build()` -> build via graph), "." = an attribute of anything else. For an import it is what was
                       imported, "module:name" (`from .graph import build as b` -> b via ".graph:build"; `import orch.graph` -> "orch:")
        note     "" or why the file got less than a full outline

Adding a language = one entry in LANGS: its file extensions, its comment marks and its declaration patterns per scope. Nothing else changes."""
import ast
import re

KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "typeof", "sizeof", "throw", "await", "yield", "foreach",
            "using", "lock", "fixed", "else", "do", "try", "super", "this", "base", "self", "fn", "func", "def", "class", "in", "of", "is",
            "as", "and", "or", "not", "case", "when", "where", "let", "var", "val", "const", "import", "export", "default", "void",
            "static", "public", "private", "protected", "internal", "struct", "interface", "enum", "impl", "mod", "use", "pub", "echo",
            "elif", "except", "finally", "with", "lambda", "raise", "from", "assert", "true", "false", "null", "nil", "undefined",
            "instanceof", "unsafe", "checked", "unchecked", "nameof", "goto", "continue", "break", "go", "defer", "isset", "unset",
            "require", "include", "require_once", "include_once"}                 # words that look like a call or a type but are the language's own
CONTROL = {"if", "for", "while", "switch", "catch", "return", "foreach", "using", "lock", "fixed", "else", "do", "try", "super", "this",
           "base", "self", "function", "typeof", "sizeof", "throw", "await", "yield", "match", "when", "case"}   # never a declaration's name
ENUMS = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
PROTOCOLS = {"Protocol", "ABC"}


def _sym(name, kind, start, end, qual, parent):
    return {"name": name, "kind": kind, "start": start, "end": max(start, end or start), "qual": qual, "parent": parent}


# ---------------------------------------------------------------- Python: exact, with ast

def _dotted(node):
    return node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else ""


def _py_symbols(tree):
    out = []

    def walk(body, parent, in_class):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([d.lineno for d in n.decorator_list] + [n.lineno])
                qual = f"{parent}.{n.name}" if parent else n.name
                if isinstance(n, ast.ClassDef):
                    bases = {_dotted(b) for b in n.bases}
                    kind = "enum" if bases & ENUMS else "interface" if bases & PROTOCOLS else "class"
                else:
                    decos = {_dotted(d.func if isinstance(d, ast.Call) else d) for d in n.decorator_list}
                    kind = "property" if in_class and decos & {"property", "cached_property", "setter", "getter", "deleter"} else "method" if in_class else "function"
                out.append(_sym(n.name, kind, start, n.end_lineno, qual, parent))
                if isinstance(n, ast.ClassDef):
                    walk(n.body, qual, True)
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    for name in (e.id for e in ast.walk(t) if isinstance(e, ast.Name)):
                        out.append(_sym(name, "field" if in_class else "variable", n.lineno, n.end_lineno, f"{parent}.{name}" if parent else name, parent))
    walk(tree.body, None, False)
    return out


def _via(node):
    if isinstance(node, ast.Name):
        return "self" if node.id in ("self", "cls") else node.id
    return "."


class _PyUses(ast.NodeVisitor):
    """Every name a line of Python uses, with how it is used. Definitions are not uses."""

    def __init__(self):
        self.out = []

    def add(self, node, name, role, via=""):
        self.out.append((node.lineno, name, role, via))

    def visit_Call(self, n):
        f = n.func
        if isinstance(f, ast.Name):
            self.add(f, f.id, "call")
        elif isinstance(f, ast.Attribute):
            self.add(f, f.attr, "call", _via(f.value))
            self.visit(f.value)
        else:
            self.visit(f)
        for a in n.args:
            self.visit(a)
        for k in n.keywords:
            self.visit(k.value)

    def visit_Name(self, n):
        self.add(n, n.id, "store" if isinstance(n.ctx, ast.Store) else "load")

    def visit_Attribute(self, n):
        self.add(n, n.attr, "store" if isinstance(n.ctx, ast.Store) else "load", _via(n.value))
        self.visit(n.value)

    def annot(self, a):
        for sub in ast.walk(a) if a is not None else ():
            if isinstance(sub, (ast.Name, ast.Attribute)):
                self.add(sub, _dotted(sub), "annot", _via(sub.value) if isinstance(sub, ast.Attribute) else "")
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):          # "Forward" references in quotes
                for w in re.findall(r"[A-Za-z_]\w*", sub.value):
                    self.add(sub, w, "annot")

    def visit_FunctionDef(self, n):
        for d in n.decorator_list:
            self.visit(d)
        a = n.args
        for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
            if arg is not None:
                self.annot(arg.annotation)
        for d in a.defaults + [d for d in a.kw_defaults if d is not None]:
            self.visit(d)
        self.annot(n.returns)
        for s in n.body:
            self.visit(s)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, n):
        for d in n.decorator_list:
            self.visit(d)
        for b in n.bases:
            if isinstance(b, (ast.Name, ast.Attribute)):
                self.add(b, _dotted(b), "base", _via(b.value) if isinstance(b, ast.Attribute) else "")
            else:
                self.visit(b)
        for k in n.keywords:
            self.visit(k.value)
        for s in n.body:
            self.visit(s)

    def visit_AnnAssign(self, n):
        self.annot(n.annotation)
        self.visit(n.target)
        if n.value is not None:
            self.visit(n.value)

    def visit_Import(self, n):
        for a in n.names:
            self.add(n, a.asname or a.name.split(".")[0], "import", (a.name if a.asname else a.name.split(".")[0]) + ":")

    def visit_ImportFrom(self, n):
        for a in n.names:
            if a.name != "*":
                self.add(n, a.asname or a.name, "import", "." * n.level + (n.module or "") + ":" + a.name)


def _py_outline_fallback(text):
    """A Python file that does not parse (a half-written change): defs and classes by indentation, no uses."""
    out, stack = [], []
    for i, ln in enumerate(text.split("\n"), 1):
        if not ln.strip():
            continue
        ind = len(ln) - len(ln.lstrip())
        while stack and ind <= stack[-1][0]:
            stack.pop()
        m = re.match(r"^(\s*)(?:async\s+)?(def|class)\s+(\w+)", ln)
        if m:
            parent = out[stack[-1][1]]["qual"] if stack else None
            kind = "class" if m.group(2) == "class" else "method" if stack and out[stack[-1][1]]["kind"] == "class" else "function"
            out.append(_sym(m.group(3), kind, i, i, f"{parent}.{m.group(3)}" if parent else m.group(3), parent))
            stack.append((ind, len(out) - 1))
        for _, idx in stack:
            out[idx]["end"] = i
    return out


def _python(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as e:
        line = getattr(e, "lineno", None)
        return _py_outline_fallback(text), [], f"syntax error{f' at line {line}' if line else ''}: outline only"
    v = _PyUses()
    v.visit(tree)
    return _py_symbols(tree), v.out, ""


# ---------------------------------------------------------------- the other languages: patterns + brace matching

def _stripper(line_comments, quotes, lifetimes):
    alts = [re.escape(m) + r"[^\n]*" for m in line_comments] + [r"/\*[\s\S]*?(?:\*/|\Z)"]
    if '"' in quotes:
        alts.append(r'"""[\s\S]*?(?:"""|\Z)')
    for q in quotes:
        if q == "`":
            alts.append(r"`(?:\\[\s\S]|[^\\`])*`?")
        elif q == "'" and lifetimes:
            alts.append(r"'(?:\\[^'\n]{1,10}|[^\\'\n])'")                    # Rust: a char literal; a lifetime ('a) has no closing quote
        else:
            alts.append(f"{q}(?:\\\\.|[^\\\\{q}\\n])*{q}?")
    return re.compile("|".join(alts))


def _blank(m):
    s = m.group(0)
    inner = "".join(ch if ch == "\n" else " " for ch in s)
    if s[0] not in "\"'`":                                                    # a comment: all gone
        return inner
    return s[0] + inner[1:-1] + s[-1] if len(s) > 1 and s[-1] == s[0] else s[0] + inner[1:]


def strip_code(text, line_comments=("//",), quotes="\"'`", lifetimes=False):
    """Comments and the inside of strings become spaces (newlines stay), so patterns and brace counting only see code."""
    return _stripper(tuple(line_comments), quotes, lifetimes).sub(_blank, text)


_NAME = r"(?P<name>[A-Za-z_$][\w$]*)"
_JS_MOD = r"(?:(?:public|private|protected|static|readonly|abstract|override|declare|async|accessor)\s+)*"
_CS_MOD = r"(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|internal|static|sealed|abstract|partial|readonly|unsafe|new|file|virtual|override|async|extern|const|volatile|required|ref)\s+)*"
_JV_MOD = r"(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|transient|volatile|strictfp|sealed|non-sealed)\s+)*"
_KT_MOD = r"(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|protected|internal|override|open|abstract|final|suspend|inline|operator|infix|tailrec|external|lateinit|const|data|sealed|enum|inner|value|annotation|expect|actual)\s+)*"
_SW_MOD = r"(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|fileprivate|internal|open|static|final|override|mutating|nonmutating|class|lazy|weak|unowned|convenience|required|dynamic|indirect)\s+)*"
_PHP_MOD = r"(?:(?:public|private|protected|static|abstract|final|readonly|var)\s+)*"
_TYPE = r"[\w.?\[\]]+(?:<[^()]*>)?[\[\]?]*"

# Each scope ("top": the file or a namespace, "class": directly inside a class/interface/trait, "impl": a Rust impl or Swift extension)
# lists (pattern, kind, what follows). What follows: "class"/"impl"/"ns" = a body with declarations inside, "fn" = a body or a `;`,
# "expr" = like fn, but a line that ends without a continuation also ends it (JS without semicolons, Kotlin `fun f() = 1`).
# A kind of None opens a scope without being a symbol (namespaces, impl blocks).
_JS_CLASS = (rf"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?class\s+{_NAME}", "class", "class")
_JS_TOP = [
    _JS_CLASS,
    (rf"^\s*(?:export\s+)?(?:declare\s+)?interface\s+{_NAME}", "interface", "class"),
    (rf"^\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+{_NAME}", "enum", "fn"),
    (r"^\s*(?:export\s+)?(?:declare\s+)?(?:namespace|module)\s+[\w$.'\"]+\s*\{", None, "ns"),
    (rf"^\s*(?:export\s+)?(?:declare\s+)?type\s+{_NAME}\s*(?:<[^=]*>)?\s*=", "type", "expr"),
    (rf"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?function\s*\*?\s*{_NAME}", "function", "fn"),
    (rf"^\s*(?:export\s+)?(?:declare\s+)?(?:const|let|var)\s+{_NAME}\s*(?::[^=]*)?=\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*(?::[^=]*)?=>|[A-Za-z_$][\w$]*\s*=>)", "function", "expr"),
    (rf"^\s*(?:export\s+)?(?:declare\s+)?(?:const|let|var)\s+{_NAME}", "variable", "expr"),
]
_JS_MEMBERS = [
    _JS_CLASS,
    (rf"^\s*{_JS_MOD}(?:get|set)\s+#?{_NAME}\s*\(", "property", "fn"),
    (rf"^\s*{_JS_MOD}\*?\s*#?{_NAME}\s*[?!]?\s*(?:<[^>()]*>)?\s*\(", "method", "fn"),
    (rf"^\s*{_JS_MOD}#?{_NAME}\s*[?!]?\s*(?::|=)", "field", "expr"),
]
_CS_TYPES = [
    (rf"^\s*{_CS_MOD}(?:record\s+(?:class|struct)\s+|record\s+|class\s+|struct\s+){_NAME}", "class", "class"),
    (rf"^\s*{_CS_MOD}interface\s+{_NAME}", "interface", "class"),
    (rf"^\s*{_CS_MOD}enum\s+{_NAME}", "enum", "fn"),
    (rf"^\s*{_CS_MOD}delegate\s+{_TYPE}\s+{_NAME}\s*\(", "type", "fn"),
]
_CS_TOP = [(r"^\s*namespace\s+[\w.]+", None, "ns"), *_CS_TYPES]
_CS_MEMBERS = [
    *_CS_TYPES,
    (rf"^\s*{_CS_MOD}(?P<name>[A-Z]\w*)\s*\(", "method", "fn"),                                       # constructor
    (rf"^\s*{_CS_MOD}{_TYPE}\s+{_NAME}\s*(?:<[^>()]*>)?\s*\(", "method", "fn"),
    (rf"^\s*{_CS_MOD}{_TYPE}\s+{_NAME}\s*(?:\{{|=>|$)", "property", "fn"),
    (rf"^\s*{_CS_MOD}{_TYPE}\s+{_NAME}\s*(?:=|;)", "field", "expr"),
]
_JV_TYPES = [
    (rf"^\s*{_JV_MOD}(?:class|record)\s+{_NAME}", "class", "class"),
    (rf"^\s*{_JV_MOD}@?interface\s+{_NAME}", "interface", "class"),
    (rf"^\s*{_JV_MOD}enum\s+{_NAME}", "enum", "class"),
]
_JV_MEMBERS = [
    *_JV_TYPES,
    (rf"^\s*{_JV_MOD}(?P<name>[A-Z]\w*)\s*\(", "method", "fn"),
    (rf"^\s*{_JV_MOD}(?:<[^>]*>\s*)?{_TYPE}\s+{_NAME}\s*\(", "method", "fn"),
    (rf"^\s*{_JV_MOD}{_TYPE}\s+{_NAME}\s*(?:=|;)", "field", "expr"),
]
_KT_TYPES = [
    (rf"^\s*{_KT_MOD}(?:class|object)\s+{_NAME}", "class", "class"),
    (rf"^\s*{_KT_MOD}(?:fun\s+)?interface\s+{_NAME}", "interface", "class"),
    (r"^\s*companion\s+object\b", None, "class"),
]
_KT_TOP = [*_KT_TYPES,
           (rf"^\s*{_KT_MOD}fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?{_NAME}\s*\(", "function", "expr"),
           (rf"^\s*{_KT_MOD}(?:val|var)\s+{_NAME}", "variable", "expr")]
_KT_MEMBERS = [*_KT_TYPES,
               (rf"^\s*{_KT_MOD}fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?{_NAME}\s*\(", "method", "expr"),
               (rf"^\s*{_KT_MOD}(?:val|var)\s+{_NAME}", "property", "expr")]
_SW_TYPES = [
    (rf"^\s*{_SW_MOD}(?:class|struct|actor)\s+{_NAME}", "class", "class"),
    (rf"^\s*{_SW_MOD}enum\s+{_NAME}", "enum", "class"),
    (rf"^\s*{_SW_MOD}protocol\s+{_NAME}", "interface", "class"),
    (rf"^\s*{_SW_MOD}extension\s+{_NAME}", None, "impl"),
]
_SW_TOP = [*_SW_TYPES, (rf"^\s*{_SW_MOD}func\s+{_NAME}", "function", "fn"), (rf"^\s*{_SW_MOD}(?:let|var)\s+{_NAME}", "variable", "expr")]
_SW_MEMBERS = [*_SW_TYPES, (rf"^\s*{_SW_MOD}func\s+{_NAME}", "method", "fn"), (r"^\s*(?:convenience\s+|required\s+)*(?P<name>init)\??\s*\(", "method", "fn"),
               (rf"^\s*{_SW_MOD}(?:let|var)\s+{_NAME}", "property", "expr")]
_GO_TOP = [
    (r"^func\s+\((?P<recv>[^)]*)\)\s*(?P<name>\w+)", "method", "fn"),
    (r"^func\s+(?P<name>\w+)", "function", "fn"),
    (r"^type\s+(?P<name>\w+)(?:\[[^\]]*\])?\s+struct\b", "class", "fn"),
    (r"^type\s+(?P<name>\w+)(?:\[[^\]]*\])?\s+interface\b", "interface", "fn"),
    (r"^type\s+(?P<name>\w+)\b", "type", "expr"),
    (r"^(?:var|const)\s+(?P<name>\w+)", "variable", "expr"),
]
_RS_FN = r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:default\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+\S+\s+)?fn\s+(?P<name>\w+)"
_RS_TOP = [
    (_RS_FN, "function", "fn"),
    (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|union)\s+(?P<name>\w+)", "class", "fn"),
    (r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+(?P<name>\w+)", "enum", "fn"),
    (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?trait\s+(?P<name>\w+)", "interface", "class"),
    (r"^\s*(?:pub(?:\([^)]*\))?\s+)?type\s+(?P<name>\w+)", "type", "expr"),
    (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const|static)\s+(?:mut\s+)?(?P<name>\w+)", "variable", "expr"),
    (r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+\w+\s*\{", None, "ns"),
    (r"^\s*(?:unsafe\s+)?impl(?:<[^{]*?>)?\s+(?:[\w:]+(?:<[^{]*?>)?\s+for\s+)?(?:[\w]+::)*(?P<name>\w+)", None, "impl"),
]
_PHP_TOP = [
    (r"^\s*namespace\s+[\w\\]+", None, "ns"),
    (r"^\s*(?:(?:abstract|final|readonly)\s+)*(?:class|trait)\s+(?P<name>\w+)", "class", "class"),
    (r"^\s*interface\s+(?P<name>\w+)", "interface", "class"),
    (r"^\s*enum\s+(?P<name>\w+)", "enum", "class"),
    (r"^\s*function\s+&?(?P<name>\w+)\s*\(", "function", "fn"),
    (r"^\s*const\s+(?P<name>\w+)", "variable", "expr"),
]
_PHP_MEMBERS = [
    (rf"^\s*{_PHP_MOD}function\s+&?(?P<name>\w+)\s*\(", "method", "fn"),
    (rf"^\s*{_PHP_MOD}const\s+(?P<name>\w+)", "field", "expr"),
    (rf"^\s*{_PHP_MOD}(?:\??[\w\\]+\s+)?\$(?P<name>\w+)", "field", "expr"),
]

# extensions -> (language, line comment marks, quote characters, rust-style lifetimes, {scope: patterns}, base-list pattern on a type's first line)
_JS = {"top": _JS_TOP, "ns": _JS_TOP, "class": _JS_MEMBERS}
_BASES_EXT = r"\bextends\s+(?P<a>[\w$.<>, ]+?)(?:\s+implements\s+(?P<b>[\w$.<>, ]+?))?\s*(?:\{|$)|\bimplements\s+(?P<c>[\w$.<>, ]+?)\s*(?:\{|$)"
_BASES_COLON = r"^[^:(]*\b(?:class|struct|interface|record|enum|object|protocol|extension|actor)\b[^:(]*?(?:\([^)]*\))?\s*:\s*(?P<a>[^{]+?)\s*(?:\{|where\b|$)"
LANGS = {
    (".js", ".jsx", ".mjs", ".cjs"): ("javascript", ("//",), "\"'`", False, _JS, _BASES_EXT),
    (".ts", ".tsx", ".mts", ".cts"): ("typescript", ("//",), "\"'`", False, _JS, _BASES_EXT),
    (".cs",): ("csharp", ("//",), "\"'", False, {"top": _CS_TOP, "ns": _CS_TOP, "class": _CS_MEMBERS}, _BASES_COLON),
    (".java",): ("java", ("//",), "\"'", False, {"top": _JV_TYPES, "ns": _JV_TYPES, "class": _JV_MEMBERS}, _BASES_EXT),
    (".kt", ".kts"): ("kotlin", ("//",), "\"'", False, {"top": _KT_TOP, "ns": _KT_TOP, "class": _KT_MEMBERS}, _BASES_COLON),
    (".swift",): ("swift", ("//",), "\"", False, {"top": _SW_TOP, "ns": _SW_TOP, "class": _SW_MEMBERS, "impl": _SW_MEMBERS}, _BASES_COLON),
    (".go",): ("go", ("//",), "\"'`", False, {"top": _GO_TOP}, None),
    (".rs",): ("rust", ("//",), "\"'", True, {"top": _RS_TOP, "ns": _RS_TOP, "class": [(_RS_FN, "method", "fn")], "impl": [(_RS_FN, "method", "fn")]}, None),
    (".php",): ("php", ("//", "#"), "\"'", False, {"top": _PHP_TOP, "ns": _PHP_TOP, "class": _PHP_MEMBERS}, _BASES_EXT),
}
PYTHON = (".py", ".pyi")
_COMPILED = {}


def _ext(path):
    name = path.rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def lang_of(path):
    """The language name for a path, or "" when the change graph has no outline for it."""
    ext = _ext(path)
    if ext in PYTHON:
        return "python"
    return next((spec[0] for exts, spec in LANGS.items() if ext in exts), "")


def _spec(path):
    ext = _ext(path)
    for exts, spec in LANGS.items():
        if ext in exts:
            if exts not in _COMPILED:
                _COMPILED[exts] = ({scope: [(re.compile(p), k, f) for p, k, f in pats] for scope, pats in spec[4].items()},
                                   re.compile(spec[5]) if spec[5] else None, _stripper(spec[1], spec[2], spec[3]))
            return spec[0], _COMPILED[exts]
    return None, None


_CONTINUES = ("=", "=>", "(", ",", ":", "?", "|", "&", "+", "-", ".", "{", "[", "<")


def _outline(code, scopes):
    """Declarations and their line ranges from comment- and string-free code: a stack of scopes, opened and closed by braces."""
    syms, depth = [], 0
    stack = [("top", 0, None, None)]                       # (scope, depth of its body, symbol index or None, qual prefix)
    waiting = None                                         # a declaration looking for its body: [symbol index, follows, qual for its scope, paren depth]

    def finish(ln):
        if waiting[0] is not None:
            syms[waiting[0]]["end"] = max(syms[waiting[0]]["start"], ln)

    for ln, text in enumerate(code.split("\n"), 1):
        scope, body_depth, _, prefix = stack[-1]
        col = 0
        pats = scopes.get(scope) if depth == body_depth else None
        if pats and (waiting is None or waiting[3] <= 0):
            for rx, kind, follows in pats:
                m = rx.match(text)
                if not m:
                    continue
                name = m.groupdict().get("name") or ""
                if kind and (not name or name in CONTROL):
                    continue
                qual = f"{prefix}.{name}" if prefix and name else name
                idx = None
                if kind:
                    parent = prefix
                    recv = (m.groupdict().get("recv") or "").strip()
                    if recv:                                                  # Go: func (s *Server) Handle() belongs to Server
                        parent = re.sub(r"\[.*\]$", "", recv.split()[-1].lstrip("*"))
                        qual = f"{parent}.{name}"
                    syms.append(_sym(name, kind, ln, ln, qual, parent))
                    idx = len(syms) - 1
                waiting = [idx, follows, qual if kind else (name or prefix), 0]
                col = m.end() - (1 if m.group(0)[-1:] in ("(", "{") else 0)         # the scanner below must see the opening ( or {
                break
        for ch in text[col:]:
            if waiting is not None:
                if ch == "(":
                    waiting[3] += 1
                    continue
                if ch == ")":
                    waiting[3] -= 1
                    continue
                if waiting[3] <= 0 and ch == ";":
                    finish(ln)
                    waiting = None
                    continue
                if waiting[3] <= 0 and ch == "{":
                    depth += 1
                    idx, follows, q, _ = waiting
                    inner = follows if follows in ("class", "impl", "ns") else "body"
                    stack.append((inner, depth, idx, q if idx is not None or follows == "impl" else prefix))
                    waiting = None
                    continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                if len(stack) > 1 and depth == stack[-1][1]:
                    closed = stack.pop()
                    if closed[2] is not None:
                        syms[closed[2]]["end"] = ln
                    waiting = None                                            # nothing declared inside a scope outlives it
                depth = max(0, depth - 1)
        if waiting is not None and waiting[1] == "expr" and waiting[3] <= 0 and text.strip() and not text.rstrip().endswith(_CONTINUES):
            finish(ln)                                                        # `const x = 1` with no semicolon ends with its line
            waiting = None
    return syms


_CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*(?:<[^<>()\n]*>)?\s*\(")
_MEMBER = re.compile(r"(?:\?\.|\.|->|::)\s*([A-Za-z_$][\w$]*)\b(?!\s*\()")
_STORE = re.compile(r"(?:\.|->|::)\s*([A-Za-z_$][\w$]*)\s*(?:[-+*/%|&^]|\?\?|<<|>>)?=(?![=>])")
_TYPEREF = re.compile(r"(?<![\w$.])([A-Z][\w$]*)\b(?!\s*\()")
_ACCESSOR = re.compile(r"(?:\?\.|\.|->|::)\s*$")
_OBJECT = re.compile(r"(?<![\w$.])(?<!->)(?<!::)([A-Za-z_$][\w$]*)\s*$")
_SELF = {"this", "self", "$this", "Self", "static", "cls"}
_JS_IMPORT = re.compile(r"""^\s*import\s+(?:type\s+)?(?:(?P<def>[\w$]+)\s*,?\s*)?(?:\{(?P<names>[^}]*)\})?\s*(?:\*\s*as\s+(?P<star>[\w$]+))?\s*from\s*['"](?P<mod>[^'"]+)['"]""")
_JS_REQUIRE = re.compile(r"""^\s*(?:const|let|var)\s+(?:\{(?P<names>[^}]*)\}|(?P<def>[\w$]+))\s*=\s*require\(\s*['"](?P<mod>[^'"]+)['"]\s*\)""")
_JVM_IMPORT = re.compile(r"^\s*import\s+(?P<static>static\s+)?(?P<mod>[\w.]+)\.(?P<name>\w+|\*)\s*;?\s*$")
_RS_USE = re.compile(r"^\s*(?:pub\s+)?use\s+(?P<mod>[\w:]+)::(?P<name>\w+)(?:\s+as\s+(?P<alias>\w+))?\s*;")
_PHP_USE = re.compile(r"^\s*use\s+(?P<mod>[\w\\]+)\\(?P<name>\w+)(?:\s+as\s+(?P<alias>\w+))?\s*;")


def _reached(text, start):
    """How the name starting at `start` was reached: "" (bare), "self", the object's name, or "." (anything else)."""
    acc = _ACCESSOR.search(text, 0, start)
    if not acc:
        return ""
    obj = _OBJECT.search(text, 0, acc.start())
    if not obj:
        return "."
    return "self" if obj.group(1) in _SELF else obj.group(1)


def _imports(lang, raw_lines):
    out = []
    for ln, text in enumerate(raw_lines, 1):
        if lang in ("javascript", "typescript"):
            m = _JS_IMPORT.match(text) or _JS_REQUIRE.match(text)
            if m:
                mod = m.group("mod")
                for local in [m.groupdict().get("def"), m.groupdict().get("star")]:
                    if local:
                        out.append((ln, local, "import", mod + ":"))
                for part in (m.group("names") or "").split(","):
                    bits = re.split(r"\s+as\s+|\s*:\s*", part.strip().removeprefix("type "))
                    if bits[0] and re.match(r"^[\w$]+$", bits[-1]):
                        out.append((ln, bits[-1], "import", f"{mod}:{bits[0]}"))
        elif lang in ("java", "kotlin"):
            m = _JVM_IMPORT.match(text)
            if m and m.group("name") != "*":
                target = f"{m.group('mod')}:{m.group('name')}" if m.group("static") else f"{m.group('mod')}.{m.group('name')}:"
                out.append((ln, m.group("name"), "import", target))
        elif lang in ("rust", "php"):
            m = (_RS_USE if lang == "rust" else _PHP_USE).match(text)
            if m:
                out.append((ln, m.group("alias") or m.group("name"), "import", f"{m.group('mod')}:{m.group('name')}"))
    return out


def _uses(lang, code_lines, raw_lines, syms, bases_rx):
    """What each line uses, by pattern: calls, member reads and writes, capitalised type names, base lists."""
    decl = {(s["start"], s["name"]) for s in syms}
    out = _imports(lang, raw_lines)
    import_lines = {u[0] for u in out}
    for ln, text in enumerate(code_lines, 1):
        if ln in import_lines or not text.strip():
            continue
        for m in _CALL.finditer(text):
            name = m.group(1)
            if name not in KEYWORDS and (ln, name) not in decl:
                out.append((ln, name, "call", _reached(text, m.start(1))))
        stores = set()
        for m in _STORE.finditer(text):
            stores.add(m.start(1))
            out.append((ln, m.group(1), "store", _reached(text, m.start(1))))
        for m in _MEMBER.finditer(text):
            if m.start(1) not in stores:
                out.append((ln, m.group(1), "load", _reached(text, m.start(1))))
        for m in _TYPEREF.finditer(text):
            name = m.group(1)
            if name not in KEYWORDS and (ln, name) not in decl:
                out.append((ln, name, "load" if name.isupper() else "annot", ""))
    if bases_rx is not None:
        for s in syms:
            if s["kind"] in ("class", "interface", "enum"):
                m = bases_rx.search(" ".join(code_lines[s["start"] - 1:min(s["start"] + 2, len(code_lines))]))
                for part in filter(None, m.groups() if m else ()):
                    for b in re.split(r",(?![^<]*>)", part):
                        name = re.sub(r"<.*", "", b).strip().split(".")[-1].split("(")[0].strip()
                        if re.match(r"^[A-Za-z_$][\w$]*$", name):
                            out.append((s["start"], name, "base", ""))
    return out


def parse(path, text):
    """(symbols, uses, note) for one file; see the module docstring."""
    if text is None:
        return [], [], ""
    lang = lang_of(path)
    if lang == "python":
        return _python(text)
    lang, compiled = _spec(path)
    if lang is None:
        return [], [], "no outline for this language: the file is one row"
    scopes, bases_rx, stripper = compiled
    code_lines = stripper.sub(_blank, text).split("\n")
    syms = _outline("\n".join(code_lines), scopes)
    return syms, _uses(lang, code_lines, text.split("\n"), syms, bases_rx), ""
