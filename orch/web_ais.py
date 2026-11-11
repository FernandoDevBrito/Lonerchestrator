"""The AIs tab of the web page: who is on, who does what, usage and budgets."""
import threading

from . import config, folder, menu, providers, usage
from .view import _json, load_events
from .webcore import Bad, route


class AisApi:
    @route("GET", "/api/ais")
    def ais(self):
        cfg = config.load(self.project)
        ais = _json(folder.of(self.project) / "ais.json").get("ais", {})
        avail = menu.available(self.project)
        on = menu.enabled(self.project, avail)
        used = {}
        for s in menu.SLOTS:
            used.setdefault(menu.assigned(cfg, s), []).append(s)
        st, _ = load_events(self.project)
        runs = sorted((folder.of(self.project) / "runs").glob("*"))
        run_id = st.get("run") or (runs[-1].name if runs else None)
        reg = providers.registry(cfg)
        return {"ais": [{"id": c, "name": reg.get(c, {}).get("name") or v.get("name") or c, "installed": v.get("installed", False),
                         "logged_in": v.get("logged_in", False),
                         "models": [{"key": menu.keyof(c, m), "model": m, "on": menu.keyof(c, m) in on, "used_by": used.get(menu.keyof(c, m), [])}
                                    for cl, m in avail if cl == c]} for c, v in ais.items() if v.get("installed") or c in ("claude", "agy")],
                "efforts": providers.EFFORTS,
                "slots": [{"slot": s, "key": menu.assigned(cfg, s), "effort": menu.effort(cfg, s),
                           "takes_effort": bool(providers.effort_for(providers.registry(cfg).get(menu.assigned(cfg, s).split("/")[0], {}), "high")), "ok": menu.assigned(cfg, s) in on or cfg.get("use") is None, "options": menu.options(self.project, s)}
                          for s in menu.SLOTS],
                "same_reviewers": menu.assigned(cfg, "qa") == menu.assigned(cfg, "cross"),
                "limits": usage.read_limits().get("claude", {}), "run_use": usage.run_totals(self.project, run_id), "all_use": usage.all_totals(self.project),
                "windows": usage.window_totals(self.project), "budgets": usage.budget_state(cfg, self.project), "budget_cfg": cfg.get("budgets") or {},
                "known": sorted(providers.registry(cfg)),
                "job": self.job()}

    def job(self):
        return {"detecting": bool(getattr(self, "_detecting", False)), "probing": bool(usage.PROBE["running"]), "msg": usage.PROBE["msg"]}

    @route("POST", "/api/ais/toggle", takes="body")
    def ais_toggle(self, body):
        key = body.get("key")
        if key not in [menu.keyof(c, m) for c, m in menu.available(self.project)]:
            raise Bad("unknown AI model")
        return {"msg": menu.toggle(self.project, key)}

    @route("POST", "/api/ais/assign", takes="body")
    def ais_assign(self, body):
        """Give a slot another model, or (with `effort`) change how hard its model thinks: "" = the CLI's default."""
        raw, cfg = config.read_raw(self.project), config.load(self.project)
        slot, eff = body.get("slot"), body.get("effort")
        key = body.get("key") or (menu.assigned(cfg, slot) if slot in menu.SLOTS else None)
        if eff is not None and eff not in ["", *providers.EFFORTS]:
            raise Bad("effort must be one of: " + ", ".join(providers.EFFORTS))
        if slot not in menu.SLOTS or (body.get("key") and key not in menu.options(self.project, slot)):
            raise Bad("that AI cannot fill that role")
        menu._assign(raw, cfg, slot, key, eff)
        config.write_raw(self.project, raw)
        return {"msg": f"{slot} -> {key}" + (f", effort {eff or 'default'}" if eff is not None else "")}

    @route("POST", "/api/budget", takes="body")
    def budget_set(self, body):
        """Your own limit for an AI (or one model): tokens, calls or USD per rolling window. A limit of 0 removes it."""
        key, unit, per = body.get("key"), body.get("unit"), body.get("per", "day")
        cfg = config.load(self.project)
        if unit not in ("tokens", "calls", "cost") or per not in usage.PERIODS or not isinstance(key, str) or key.split("/")[0] not in providers.registry(cfg):
            raise Bad("budget: pick an AI, tokens/calls/cost and a period (5h, day, week, month)")
        try:
            limit = float(body.get("limit", 0))
        except (TypeError, ValueError):
            raise Bad("the limit must be a number") from None
        if not 0 <= limit <= 1e12:
            raise Bad("the limit must be 0 (remove) or a positive number")
        raw = config.read_raw(self.project)
        b = raw.setdefault("budgets", {}).setdefault(key, {})
        b["per"] = per
        if limit:
            b[unit] = int(limit) if unit != "cost" else limit
        else:
            b.pop(unit, None)
        if not any(b.get(u) for u in ("tokens", "calls", "cost")):
            raw["budgets"].pop(key, None)
        config.write_raw(self.project, raw)
        return {"msg": f"{key}: " + (f"{unit} limit {limit:g} per {per}" if limit else f"{unit} limit removed")}

    @route("POST", "/api/ais/detect")
    def ais_detect(self):
        if getattr(self, "_detecting", False):
            return {"msg": "already detecting"}
        from . import intro
        self._detecting = True

        def work():
            try:
                intro.save_ais(self.project, intro.detect(config.load(self.project)))
            finally:
                self._detecting = False
        threading.Thread(target=work, daemon=True).start()
        return {"msg": "checking which AIs are installed and logged in (a few seconds)"}

    @route("POST", "/api/ais/limits")
    def ais_limits(self):
        usage.probe_in_background(self.project)
        return {"msg": "asking Claude Code for your current limits"}
