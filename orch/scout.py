"""Studying the project so the agents are not blind: fills `context/project.md` (what it is, stack, how to run/test/lint/build, conventions)
when it is empty. Agents read that file before every card.

1. `gather()` collects plain facts from the repository itself (file tree, languages, manifests, scripts, CI, README start, recent commits).
   It needs no AI and never reads secrets (.env and key files are skipped).
2. The AI with the `suggester` role (read-only, it only sees those facts) writes the file. With no AI, `render_basic()` writes the facts as they are.
A file the user already filled in is never touched unless they ask (`lonerchestrator context --force`)."""
import json
import re
from collections import Counter
from pathlib import Path

from . import folder, suggest
from .gitops import Git
from .safe import clean

MARK = "<!-- drafted by lonerchestrator from the repository; edit it freely, it is not overwritten -->"
LABELS = ["What it is", "Stack", "How to run / test / lint / build", "Conventions", "Things agents must never do here"]
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", "target", ".next", ".orchestrator", "vendor", ".idea", ".vscode", "coverage"}
SECRET = re.compile(r"(^\.env|\.pem$|\.key$|id_rsa|secrets?\.|credentials)", re.IGNORECASE)
LANGS = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript (React)", ".ts": "TypeScript", ".tsx": "TypeScript (React)", ".go": "Go", ".rs": "Rust", ".java": "Java",
         ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C", ".swift": "Swift", ".sql": "SQL", ".sh": "Shell", ".vue": "Vue",
         ".svelte": "Svelte", ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".ipynb": "Jupyter notebooks", ".r": "R"}
MAX_FILE = 200_000


def filled(project):
    """True when context/project.md (in the project's folder) already has real content (comments, headings and empty bullets do not count)."""
    f = folder.of(project) / "context" / "project.md"
    if not f.is_file():
        return False
    body = [ln for ln in re.sub(r"<!--.*?-->", "", f.read_text(encoding="utf-8", errors="replace"), flags=re.DOTALL).splitlines() if ln.strip() and not ln.startswith("#")]
    return any(len(ln.split(":", 1)[-1].strip()) > 3 for ln in body)


def _read(path, limit=4000):
    try:
        if path.stat().st_size > MAX_FILE or SECRET.search(path.name):
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _files(project):
    """Tracked files when this is a git repository, else a walk; always without vendored/build folders and secrets."""
    try:
        names = Git(project).out("ls-files").splitlines()
    except (RuntimeError, OSError):
        names = []
    if not names:
        names = [str(p.relative_to(project)).replace("\\", "/") for p in Path(project).rglob("*") if p.is_file() and not (set(p.relative_to(project).parts) & SKIP_DIRS)]
    return sorted(n for n in names if not (set(Path(n).parts) & SKIP_DIRS) and not SECRET.search(Path(n).name))[:5000]


def _json(path):
    try:
        return json.loads(_read(path, MAX_FILE))
    except ValueError:
        return {}


def lead(text):
    """The first sentences of prose in a README: no title, badges, links, images, tables or code."""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s[0] in "#[!<|>`-*=" or s.startswith(("```", "---", "===")):
            continue
        s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"", s)
        s = re.sub(r"[*_`]", "", s).strip()
        if len(s) > 15:
            out.append(s)
        if len(" ".join(out)) > 200:
            break
    return " ".join(out)[:300]


MANIFESTS = ("requirements.txt", "requirements-dev.txt", "Pipfile", "setup.py", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "Gemfile", "composer.json")
TOOL_FILES = (("Dockerfile", "Docker"), ("docker-compose.yml", "Docker Compose"), ("tsconfig.json", "TypeScript config"), (".editorconfig", "EditorConfig"),
              (".prettierrc", "Prettier"), ("ruff.toml", "Ruff"), ("tox.ini", "tox"), ("pytest.ini", "pytest"), (".pre-commit-config.yaml", "pre-commit"))


class Found:
    """What the detectors fill in. `add(kind, cmd)` keeps every command found: a mixed repo has more than one `test`."""

    def __init__(self, project, files):
        self.project, self.files = project, files
        self.facts = {"manifests": {}, "commands": {}, "tools": [], "ci": [], "tests": [], "git": []}

    def add(self, kind, cmd):
        if cmd not in self.facts["commands"].setdefault(kind, []):
            self.facts["commands"][kind].append(cmd)


# Each detector looks for one ecosystem or one kind of fact and reports into Found. To support a new one, write a function and add it to DETECTORS.
def detect_node(f):
    pj = _json(f.project / "package.json")
    if not pj:
        return
    deps = sorted({*pj.get("dependencies", {}), *pj.get("devDependencies", {})})
    f.facts["manifests"]["package.json"] = f"name {pj.get('name', '?')}; {pj.get('description', '')}; dependencies: {', '.join(deps[:20])}"
    runner = "pnpm" if (f.project / "pnpm-lock.yaml").exists() else "yarn" if (f.project / "yarn.lock").exists() else "npm"
    for key in ("dev", "start", "test", "lint", "build", "format", "typecheck"):
        if key in pj.get("scripts", {}):
            f.add(key, f"{runner} test" if key == "test" else f"{runner} run {key}" if runner == "npm" else f"{runner} {key}")


def detect_python(f):
    py = _read(f.project / "pyproject.toml")
    if not py:
        return
    name = re.search(r'^name\s*=\s*"([^"]+)"', py, re.MULTILINE)
    f.facts["manifests"]["pyproject.toml"] = f"name {name.group(1) if name else '?'}; " + "; ".join(sorted(set(re.findall(r"^\[tool\.([a-z0-9_-]+)", py, re.MULTILINE)))[:8])
    if "pytest" in py:
        f.add("test", "python -m pytest")
    if "[tool.ruff" in py:
        f.add("lint", "ruff check .")


def detect_manifests(f):
    for name in MANIFESTS:
        text = _read(f.project / name, 1500)
        if text:
            f.facts["manifests"][name] = " ".join(text.split())[:260]


def detect_rust_go(f):
    for marker, cmds in (("Cargo.toml", (("test", "cargo test"), ("build", "cargo build"))), ("go.mod", (("test", "go test ./..."), ("build", "go build ./...")))):
        if (f.project / marker).exists():
            for kind, cmd in cmds:
                f.add(kind, cmd)


def detect_make(f):
    mk = _read(f.project / "Makefile")
    if not mk:
        return
    targets = re.findall(r"^([a-zA-Z][\w-]*):", mk, re.MULTILINE)
    f.facts["manifests"]["Makefile"] = "targets: " + ", ".join(targets[:14])
    for key in ("test", "lint", "build", "dev", "run", "check"):
        if key in targets:
            f.add(key, f"make {key}")


def detect_ci_script(f):
    if (f.project / "scripts" / "ci.sh").is_file():
        f.add("ci", "bash scripts/ci.sh")


def detect_tooling(f):
    f.facts["tools"] += [label for name, label in TOOL_FILES if (f.project / name).exists()]
    f.facts["tools"] += [f"ESLint ({p.name})" for p in f.project.glob(".eslintrc*")] + (["ESLint (flat config)"] if any(f.project.glob("eslint.config.*")) else [])


def detect_ci_workflows(f):
    for wf in sorted((f.project / ".github" / "workflows").glob("*.y*ml"))[:3]:
        f.facts["ci"].append(f"{wf.name}: " + "; ".join(re.findall(r"^\s*-?\s*run:\s*(.+)$", _read(wf), re.MULTILINE)[:5]))


def detect_tests(f):
    f.facts["tests"] = sorted({n.split("/")[0] for n in f.files if re.search(r"(^|/)(tests?|__tests__|spec)(/|$)|(_test|\.test|\.spec)\.\w+$", n)})[:6]


def detect_history(f):
    try:
        f.facts["git"] = [ln[:90] for ln in Git(f.project).out("log", "-8", "--format=%s").splitlines() if ln.strip()]
    except (RuntimeError, OSError):
        pass


DETECTORS = [detect_node, detect_python, detect_manifests, detect_rust_go, detect_make, detect_ci_script, detect_tooling, detect_ci_workflows, detect_tests, detect_history]


def gather(project):
    """The facts: {"files": n, "languages": [...], "top": [...], "manifests": {...}, "commands": {...}, "readme": str, "lead": str, "ci": [...], "tests": [...], "git": [...], "tools": [...]}."""
    project = Path(project)
    files = _files(project)
    langs = Counter(LANGS[Path(n).suffix.lower()] for n in files if Path(n).suffix.lower() in LANGS)
    top = Counter(n.split("/")[0] + "/" for n in files if "/" in n)         # folders only: loose root files are noise
    found = Found(project, files)
    for detect in DETECTORS:
        detect(found)
    raw = next((_read(project / n, 2500) for n in ("README.md", "README.rst", "README.txt", "README") if (project / n).is_file()), "")
    return {"files": len(files), "languages": [f"{k} ({v} files)" for k, v in langs.most_common(6)],
            "top": [f"{k} ({v} files)" for k, v in sorted(top.items(), key=lambda kv: (-kv[1], kv[0]))[:14] if not k.startswith(".")] or ["no folders: everything is in the root"],
            "readme": " ".join(raw.split())[:1200], "lead": lead(raw), **found.facts}


def facts_text(facts):
    rows = [f"Files tracked: {facts['files']}", "Languages: " + (", ".join(facts["languages"]) or "none detected"), "Top level: " + (", ".join(facts["top"]) or "empty")]
    rows += [f"{k}: {v}" for k, v in facts["manifests"].items()]
    rows.append("Commands found: " + ("; ".join(f"{k} = {' | '.join(v)}" for k, v in facts["commands"].items()) or "none"))
    rows += ["Tooling: " + ", ".join(facts["tools"]) if facts["tools"] else "Tooling: none detected"]
    rows += ["CI: " + c for c in facts["ci"]] + (["Test folders/files: " + ", ".join(facts["tests"])] if facts["tests"] else ["Tests: none found"])
    rows += (["README start: " + facts["readme"]] if facts["readme"] else []) + (["Recent commits: " + " | ".join(facts["git"])] if facts["git"] else [])
    return clean("\n".join(rows))[:7000]


def render_basic(facts):
    """project.md straight from the facts (no AI): every line is something found in the repository, the rest says so."""
    cmds = "; ".join(f"{k}: {' | '.join(v)}" for k, v in facts["commands"].items()) or "not detected: ask the user (no test/lint/build command found)"
    stack = ", ".join(facts["languages"][:4]) or "not detected"
    stack += (" · " + ", ".join(sorted({*facts["tools"]}))) if facts["tools"] else ""
    what = facts["lead"] or "no README prose found: describe it here"
    conv = ("Layout: " + ", ".join(t.split(" (")[0] for t in facts["top"][:10])) + ("; tests in " + ", ".join(facts["tests"]) if facts["tests"] else "; no tests found")
    return (f"# Project context\n\n{MARK}\n- What it is: {what}\n- Stack: {stack}\n- How to run / test / lint / build (one command each): {cmds}\n"
            f"- Conventions (naming, structure, style): {conv}. Follow the style of the surrounding code.\n"
            "- Things agents must never do here: edit .claude/, CLAUDE.md or GEMINI.md; deploy; commit secrets; touch files outside the card's scope.\n")


def prompt(facts):
    return (
        "You write the `context/project.md` that AI coding agents read before every task in this repository. Use ONLY the facts below, which come from the repository: "
        "never invent a command, a framework or a convention. Where a fact is missing, write `unknown: ask the user`.\n"
        "Reply with ONLY the file content in Markdown, exactly this shape, one bullet each (a bullet may be 1-3 short sentences or `;`-separated items):\n"
        "# Project context\n"
        "- What it is: ...\n- Stack: ...\n- How to run / test / lint / build (one command each): ...\n- Conventions (naming, structure, style): ...\n"
        "- Things agents must never do here: ...\n"
        "The last bullet always includes: edit .claude/, CLAUDE.md or GEMINI.md, deploy, commit secrets.\n\n"
        f"<<<FACTS\n{facts_text(facts)}\nFACTS>>>")


def parse(reply):
    """The file content from an AI reply, or None when it does not have the five bullets."""
    text = re.sub(r"^```\w*\n|\n```\s*$", "", (reply or "").strip())
    start = text.find("# Project context")
    text = text[start:] if start >= 0 else "# Project context\n" + text
    if not all(re.search(rf"^- {re.escape(label)}[^:\n]*:\s*\S", text, re.MULTILINE) for label in LABELS):
        return None
    lines = [ln.rstrip() for ln in clean(text).splitlines()][:40]
    head = lines[0]
    return head + "\n\n" + MARK + "\n" + "\n".join(ln for ln in lines[1:] if ln.strip()) + "\n"


def study(project, ask=None, use_ai=True):
    """(content, source) for context/project.md: "ai" or "basic"."""
    facts = gather(project)
    if use_ai:
        try:
            got = parse((ask or suggest.asker(project))(prompt(facts)))
        except Exception:                      # noqa: BLE001  (an AI that cannot be reached must never stop the run)
            got = None
        if got:
            return got, "ai"
    return render_basic(facts), "basic"


def ensure(project, ask=None, use_ai=True, force=False, say=print):
    """Fill context/project.md (in the project's folder) when it is empty, or always with `force`. Returns the source ("ai"/"basic")
    or None when nothing was needed."""
    project = Path(project)
    if filled(project) and not force:
        return None
    say("studying the project to fill context/project.md (the agents read it before every card)...")
    content, source = study(project, ask, use_ai)
    f = folder.of(project) / "context" / "project.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    say(f"{f.as_posix()} written from the repository ({'drafted by the AI' if source == 'ai' else 'from the facts found, no AI answered'}): "
        "read it and correct anything wrong.")
    return source

