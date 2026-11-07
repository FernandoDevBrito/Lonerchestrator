"""Cards are markdown files in board/<state>/. Front matter: title, area, attempts."""
import re
import shutil
import time
from pathlib import Path

STATES = ("backlog", "doing", "review", "done", "blocked")
AREAS = ("frontend", "backend", "both")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


class Card:
    def __init__(self, path):
        self.path = Path(path)

    @property
    def id(self):
        return self.path.stem

    def text(self):
        return self.path.read_text(encoding="utf-8")

    def get(self, key, default=""):
        m = re.search(rf"^{key}:[ \t]*(.*)$", self.text(), re.MULTILINE)
        return re.sub(r"\s+#.*$", "", m.group(1)).strip() if m else default

    def set(self, key, value):
        t = self.text()
        if re.search(rf"^{key}:", t, re.MULTILINE):
            t = re.sub(rf"^{key}:.*$", f"{key}: {value}", t, count=1, flags=re.MULTILINE)
        else:
            t = t.replace("---\n", f"---\n{key}: {value}\n", 1)
        self.path.write_text(t, encoding="utf-8")

    @property
    def title(self):
        return self.get("title", self.id)

    @property
    def area(self):
        return self.get("area", "backend")

    def section(self, name):
        m = re.search(rf"^## +{re.escape(name)}[^\n]*\n(.*?)(?=^## |\Z)", self.text(), re.MULTILINE | re.DOTALL)
        return _COMMENT.sub("", m.group(1)).strip() if m else ""

    def set_section(self, name, text):
        """Replace the body of '## <name>...' (empty text clears it); insert the section before the status log when missing."""
        t = self.text()
        pat = re.compile(rf"(^## +{re.escape(name)}[^\n]*\n)(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
        body = (text.strip() + "\n\n") if text.strip() else "\n"
        if pat.search(t):
            t = pat.sub(lambda m: m.group(1) + body, t, count=1)
        else:
            i = t.find("## Status log")
            block = f"## {name}\n{body}"
            t = t[:i] + block + t[i:] if i >= 0 else t.rstrip() + "\n\n" + block
        self.path.write_text(t, encoding="utf-8")

    def log(self, msg):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"- {time.strftime('%F %T')} {msg}\n")

    def for_review(self):
        """Card as the independent reviewers see it: no plan, tasks, blockers or status log."""
        out, skip = [], False
        for line in self.text().splitlines():
            if line.startswith("## "):
                skip = bool(re.match(r"## +(Plan|Tasks|Blockers|Status log)", line))
            if not skip:
                out.append(line)
        return "\n".join(out)

    def problems(self):
        """Structural checks only; vagueness is judged by the planner agent."""
        p = []
        if self.area not in AREAS:
            p.append(f"area must be one of {AREAS}, got '{self.area}'")
        if not self.section("Goal") or self.section("Goal").startswith("<"):
            p.append("Goal is empty")
        crit = [c for c in re.findall(r"^- \[[ x]\] (.+)$", self.section("Acceptance criteria"), re.MULTILINE) if not c.startswith("<")]
        if not crit:
            p.append("no acceptance criteria (- [ ] ...)")
        return p

    def move(self, state):
        dest = self.path.parent.parent / state
        dest.mkdir(exist_ok=True)
        self.path = Path(shutil.move(str(self.path), str(dest / self.path.name)))


class Board:
    def __init__(self, project):
        self.root = Path(project) / "board"

    def ensure(self):
        for s in STATES:
            (self.root / s).mkdir(parents=True, exist_ok=True)
            (self.root / s / ".gitkeep").touch()

    def cards(self, state):
        return [Card(p) for p in sorted((self.root / state).glob("*.md"))]

    def counts(self):
        return {s: len(self.cards(s)) for s in STATES}
