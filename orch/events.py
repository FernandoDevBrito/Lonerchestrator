"""Logging: structured events (jsonl), live per-role streams (tailed by the panes), human table."""
import json
import threading
import time
from pathlib import Path

from .safe import clean

STREAMS = ("pipeline", "planner", "builder", "qa", "cross", "retro")
ALIAS = {"splitter": "planner"}   # splitter shares the planner pane


class Log:
    def __init__(self, project, echo=True):
        self.project = Path(project)
        self.root = self.project / ".orchestrator"
        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        self.dir = self.root / "runs" / self.run_id
        self.streams_dir = self.root / "streams"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.streams_dir.mkdir(exist_ok=True)
        self.table = self.project / "board" / "_log.md"
        self.echo = echo
        self._lock = threading.RLock()
        self._active = {}                    # cards being worked on right now (several when cards run in parallel): id -> phase
        for s in STREAMS:
            (self.streams_dir / f"{s}.log").write_text(f"--- run {self.run_id} ---\n", encoding="utf-8")
        if not self.table.exists():
            self.table.parent.mkdir(exist_ok=True)
            self.table.write_text("| time | card | agent | result | duration |\n|---|---|---|---|---|\n", encoding="utf-8")

    def say(self, stream, text):
        stream = ALIAS.get(stream, stream)
        with self._lock:
            with (self.streams_dir / f"{stream}.log").open("a", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
            if stream == "pipeline" and self.echo:
                print(clean(text.rstrip()), flush=True)

    def event(self, kind, card="-", agent="-", result="", secs=0.0, **extra):
        rec = {"ts": time.strftime("%F %T"), "kind": kind, "card": card, "agent": agent, "result": result, "secs": round(secs, 1), **extra}
        with self._lock:
            with (self.dir / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            with self.table.open("a", encoding="utf-8") as f:
                f.write(f"| {rec['ts']} | {card} | {agent} | {result or kind} | {secs:.0f}s |\n")
        self.say("pipeline", f"{time.strftime('%H:%M:%S')}  {card.split('-')[0]:<4} {agent:<12} {result or kind}" + (f"  ({secs:.0f}s)" if secs >= 1 else ""))

    def artifact(self, card, name, text):
        d = self.dir / card
        d.mkdir(exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")
        return d / name

    def state(self, **kw):
        with self._lock:
            if kw.get("card"):
                self._active[kw["card"]] = kw.get("phase", "")
            elif "card" in kw:
                self._active.clear()
            self._write(kw)

    def _write(self, kw):
        data = {"run": self.run_id, "ts": time.strftime("%F %T"), **kw, "active": dict(self._active)}
        (self.root / "state.json").write_text(json.dumps(data), encoding="utf-8")

    def finish(self, cid):
        """A card left the pipeline: show the most recent card that is still running, or idle."""
        with self._lock:
            self._active.pop(cid, None)
            card, phase = list(self._active.items())[-1] if self._active else (None, "idle")
            self._write({"card": card, "phase": phase})
