"""The Settings tab of the web page: readiness checks, settings, and studying the project."""
import threading

from . import checks, config, settings
from .webcore import Bad, route


class SettingsApi:
    @route("GET", "/api/settings")
    def settings(self):
        cfg = config.load(self.project)
        out = []
        for key, label, kind, options, unit, help_ in settings.SPEC:
            out.append({"key": key, "label": label, "kind": kind, "unit": unit, "help": help_, "value": settings.get(cfg, key),
                        "options": settings.branches(self.project) if kind == "branch" else options})
        checks_ = [{"status": s, "title": t, "hint": h, "action": "context" if t.startswith("context/project.md is empty") else ""} for s, t, h in checks.readiness(self.project)]
        ready, summary = checks.summary([(c["status"], c["title"], c["hint"]) for c in checks_])
        return {"settings": out, "checks": checks_, "ready": ready, "summary": summary}

    @route("POST", "/api/settings/set", takes="body")
    def settings_set(self, body):
        key = body.get("key")
        try:
            if key not in settings.KEYS:
                raise ValueError("unknown setting")
            msg = settings.set_text(self.project, key, str(body.get("value", ""))) if settings.spec(key)[2] == "text" else settings.set_value(self.project, key, body.get("value"))
        except ValueError as e:
            raise Bad(str(e)) from None
        return {"msg": msg}

    @route("POST", "/api/context")
    def context_study(self):
        """Have the AI study the repository and fill context/project.md (a few seconds, so it runs in the background)."""
        from . import scout
        if getattr(self, "_studying", False):
            return {"msg": "already studying the project"}
        if scout.filled(self.project):
            return {"msg": "context/project.md already has content: it is never overwritten (use `lonerchestrator context --force`)"}
        self._studying = True

        def work():
            try:
                scout.ensure(self.project, say=lambda *_: None)
            finally:
                self._studying = False
        threading.Thread(target=work, daemon=True).start()
        return {"msg": "studying the project: context/project.md will be filled in a few seconds"}
