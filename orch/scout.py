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

from . import suggest
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
    """True when context/project.md already has real content (comments, headings and empty bullets do not count)."""
    f = Path(project) / "context" / "project.md"
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
    return sorted(n for n in names if not (set(Path(n).parts) & SKIP_DIRS) and not SECRET.search(Path(n).name) and not n.startswith("board/"))[:5000]


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


def gather(project):
    """The facts: {"files": n, "languages": [...], "top": [...], "manifests": {...}, "commands": {...}, "readme": str, "ci": [...], "tests": [...], "git": [...], "tools": [...]}."""
    project = Path(project)
    files = _files(project)
    langs = Counter(LANGS[Path(n).suffix.lower()] for n in files if Path(n).suffix.lower() in LANGS)
    top = Counter(n.split("/")[0] + "/" for n in files if "/" in n)         # folders only: loose root files are noise
    commands = {}                                                     # {kind: [every command found]}: a mixed repo has more than one `test`

    def add(kind, cmd):
        if cmd not in commands.setdefault(kind, []):
            commands[kind].append(cmd)
    facts = {"files": len(files), "languages": [f"{k} ({v} files)" for k, v in langs.most_common(6)],
             "top": [f"{k} ({v} files)" for k, v in sorted(top.items(), key=lambda kv: (-kv[1], kv[0]))[:14] if not k.startswith(".")] or ["no folders: everything is in the root"], "manifests": {}, "commands": commands, "tools": [], "ci": [], "tests": []}
    pj = _json(project / "package.json")
    if pj:
        deps = sorted({*pj.get("dependencies", {}), *pj.get("devDependencies", {})})
        facts["manifests"]["package.json"] = f"name {pj.get('name', '?')}; {pj.get('description', '')}; dependencies: {', '.join(deps[:20])}"
        for key in ("dev", "start", "test", "lint", "build", "format", "typecheck"):
            if key in pj.get("scripts", {}):
                runner = "pnpm" if (project / "pnpm-lock.yaml").exists() else "yarn" if (project / "yarn.lock").exists() else "npm"
                add(key, f"{runner} test" if key == "test" else f"{runner} run {key}" if runner == "npm" else f"{runner} {key}")
    py = _read(project / "pyproject.toml")
    if py:
        name = re.search(r'^name\s*=\s*"([^"]+)"', py, re.MULTILINE)
        facts["manifests"]["pyproject.toml"] = f"name {name.group(1) if name else '?'}; " + "; ".join(sorted(set(re.findall(r"^\[tool\.([a-z0-9_-]+)", py, re.MULTILINE)))[:8])
        if "pytest" in py:
            add("test", "python -m pytest")
        if "[tool.ruff" in py:
            add("lint", "ruff check .")
    for name in ("requirements.txt", "requirements-dev.txt", "Pipfile", "setup.py", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "Gemfile", "composer.json"):
        text = _read(project / name, 1500)
        if text:
            facts["manifests"][name] = " ".join(text.split())[:260]
    if (project / "Cargo.toml").exists():
        add("test", "cargo test")
        add("build", "cargo build")
    if (project / "go.mod").exists():
        add("test", "go test ./...")
        add("build", "go build ./...")
    mk = _read(project / "Makefile")
    if mk:
        targets = re.findall(r"^([a-zA-Z][\w-]*):", mk, re.MULTILINE)
        facts["manifests"]["Makefile"] = "targets: " + ", ".join(targets[:14])
        for key in ("test", "lint", "build", "dev", "run", "check"):
            if key in targets:
                add(key, f"make {key}")
    if (project / "scripts" / "ci.sh").is_file():
        add("ci", "bash scripts/ci.sh (the orchestrator's CI command)")
    for name, label in (("Dockerfile", "Docker"), ("docker-compose.yml", "Docker Compose"), ("tsconfig.json", "TypeScript config"), (".editorconfig", "EditorConfig"),
                        (".prettierrc", "Prettier"), ("ruff.toml", "Ruff"), ("tox.ini", "tox"), ("pytest.ini", "pytest"), (".pre-commit-config.yaml", "pre-commit")):
        if (project / name).exists():
            facts["tools"].append(label)
    facts["tools"] += [f"ESLint ({p.name})" for p in project.glob(".eslintrc*")] + (["ESLint (flat config)"] if any(project.glob("eslint.config.*")) else [])
    for wf in sorted((project / ".github" / "workflows").glob("*.y*ml"))[:3]:
        facts["ci"].append(f"{wf.name}: " + "; ".join(re.findall(r"^\s*-?\s*run:\s*(.+)$", _read(wf), re.MULTILINE)[:5]))
    facts["tests"] = sorted({n.split("/")[0] for n in files if re.search(r"(^|/)(tests?|__tests__|spec)(/|$)|(_test|\.test|\.spec)\.\w+$", n)})[:6]
    raw = next((_read(project / n, 2500) for n in ("README.md", "README.rst", "README.txt", "README") if (project / n).is_file()), "")
    facts["readme"], facts["lead"] = " ".join(raw.split())[:1200], lead(raw)
    try:
        log = Git(project).out("log", "-8", "--format=%s").splitlines()
        facts["git"] = [ln[:90] for ln in log if ln.strip()]
    except (RuntimeError, OSError):
        facts["git"] = []
    return facts


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
            "- Things agents must never do here: edit scripts/, .claude/, CLAUDE.md or GEMINI.md; deploy; commit secrets; touch files outside the card's scope.\n")


def prompt(facts):
    return (
        "You write the `context/project.md` that AI coding agents read before every task in this repository. Use ONLY the facts below, which come from the repository: "
        "never invent a command, a framework or a convention. Where a fact is missing, write `unknown: ask the user`.\n"
        "Reply with ONLY the file content in Markdown, exactly this shape, one bullet each (a bullet may be 1-3 short sentences or `;`-separated items):\n"
        "# Project context\n"
        "- What it is: ...\n- Stack: ...\n- How to run / test / lint / build (one command each): ...\n- Conventions (naming, structure, style): ...\n"
        "- Things agents must never do here: ...\n"
        "The last bullet always includes: edit scripts/, .claude/, CLAUDE.md or GEMINI.md, deploy, commit secrets.\n\n"
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


def ensure(project, ask=None, use_ai=True, force=False, say=print, commit=True):
    """Fill context/project.md when it is empty (or always with `force`). Returns the source ("ai"/"basic") or None when nothing was needed.
    The file is committed when the working tree was clean, so a run can start right after."""
    project = Path(project)
    if filled(project) and not force:
        return None
    say("studying the project to fill context/project.md (the agents read it before every card)...")
    content, source = study(project, ask, use_ai)
    f = project / "context" / "project.md"
    f.parent.mkdir(exist_ok=True)
    git = Git(project)
    was_clean = False
    try:
        was_clean = git.clean()
    except (RuntimeError, OSError):
        pass
    f.write_text(content, encoding="utf-8")
    if commit and was_clean:
        try:
            git.run("add", "context/project.md")
            git.commit("context: project overview drafted by lonerchestrator")
        except RuntimeError:
            pass
    say(f"context/project.md written from the repository ({'drafted by the AI' if source == 'ai' else 'from the facts found, no AI answered'}"
        f"{'' if was_clean or not commit else '; your working tree has changes, so it is not committed yet'}): read it and correct anything wrong.")
    return source

