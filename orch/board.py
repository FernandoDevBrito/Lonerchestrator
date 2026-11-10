"""Cards are markdown files in board/<state>/. Front matter: title, area, attempts."""
import re
import shutil
import time
from pathlib import Path

from .safe import clean

STATES = ("backlog", "doing", "review", "done", "blocked")
AREAS = ("frontend", "backend", "both", "docs")      # the default areas; a project's own are config.areas(cfg)
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
        return clean(re.sub(r"\s+#.*$", "", m.group(1)).strip()) if m else default

    def set(self, key, value):
        t = self.text()
        if re.search(rf"^{key}:", t, re.MULTILINE):
            t = re.sub(rf"^{key}:.*$", f"{key}: {value}", t, count=1, flags=re.MULTILINE)
        else:
            t = t.replace("---\n", f"---\n{key}: {value}\n", 1)
        self.path.write_text(t, encoding="utf-8")

    def priority(self):
        try:
            return int(self.get("priority", "") or 1000)
        except ValueError:
            return 1000

    @property
    def title(self):
        return self.get("title", self.id)

    @property
    def area(self):
        return self.get("area", "backend")

    def section(self, name):
        m = re.search(rf"^## +{re.escape(name)}[^\n]*\n(.*?)(?=^## |\Z)", self.text(), re.MULTILINE | re.DOTALL)
        return clean(_COMMENT.sub("", m.group(1)).strip()) if m else ""

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

    def problems(self, areas=AREAS):
        """Structural checks only; vagueness is judged by the planner agent. `areas`: the project's (config.areas)."""
        p = []
        if self.area not in areas:
            p.append(f"area must be one of {', '.join(areas)}, got '{self.area}'")
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


def create_card(project, title, area="backend", goal=None, criteria=None):
    """A new card in board/backlog from the template. `goal`/`criteria` fill it in when the request is already written. Returns its path."""
    board = Board(project)
    nums = [int(m.group(1)) for s in STATES for c in board.cards(s) if (m := re.match(r"(\d+)-", c.id))]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "request"
    dest = board.root / "backlog" / f"{max(nums, default=0) + 1:03d}-{slug}.md"
    tpl = Path(project) / "board" / "_TEMPLATE.md"
    if not tpl.is_file():                                   # a project made by hand: use the packaged template
        tpl = Path(__file__).parent / "templates" / "board" / "_TEMPLATE.md"
    t = tpl.read_text(encoding="utf-8")
    t = t.replace("title: <short title>", f"title: {title}").replace("area: backend ", f"area: {area} ").replace("# <short title>", f"# {title}")
    if goal:
        t = t.replace("<What I want and why, in plain words.>", goal)
    if criteria:
        t = re.sub(r"(## Acceptance criteria\n(?:<!--.*?-->\n)?)(?:- \[ \] .*\n)+", lambda m: m.group(1) + "".join(f"- [ ] {c}\n" for c in criteria), t, count=1, flags=re.DOTALL)
    dest.write_text(t, encoding="utf-8")
    return dest


class Board:
    def __init__(self, project):
        self.root = Path(project) / "board"

    def ensure(self):
        for s in STATES:
            (self.root / s).mkdir(parents=True, exist_ok=True)
            (self.root / s / ".gitkeep").touch()

    def cards(self, state):
        """Cards of a column. A card may say `priority: 10` in its header (lower runs first); without it the file name decides."""
        cards = [Card(p) for p in sorted((self.root / state).glob("*.md"))]
        if state == "backlog":
            cards.sort(key=lambda c: c.priority())
        return cards

    def ready(self, card):
        """A card with `depends: 001-a, 002-b` waits until those cards are in done/ (or no longer exist anywhere)."""
        deps = [d for d in re.split(r"[,\s]+", card.get("depends")) if d]
        return all(not any((self.root / s / f"{d}.md").exists() for s in STATES if s != "done") for d in deps)

    def counts(self):
        return {s: len(self.cards(s)) for s in STATES}
