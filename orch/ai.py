"""One object per AI the orchestrator can use (Strategy). Callers say WHAT they want (a role, a prompt, edit or read); each AI knows HOW to be called.

    ClaudeCode   native: its own agents (.claude/agents/<name>.md), permissions and stream
    GenericCLI   anything described in the provider registry: the role text and project rules travel inside the prompt

Adding an AI with an integration of its own is a new subclass; adding one that only needs a command line is a `providers` entry, no code."""
import shutil

from . import providers


def _eff(effort):
    """Only pass effort when one is set, so runners (and test fakes) without it keep working."""
    return {"effort": effort} if effort else {}


class AI:
    native = False

    def __init__(self, spec):
        self.spec = spec

    @property
    def id(self):
        return self.spec["id"]

    @property
    def name(self):
        return self.spec["name"]

    @property
    def can_edit(self):
        return self.spec["can_edit"]

    def installed(self):
        return bool(shutil.which(self.spec["exe"]))

    def call(self, run, role, agent, model, prompt, mode, instructions, effort=None):
        """One live call for a pipeline role. `effort` (low..max) is how hard the model thinks; None = the CLI's default. `run` is the guarded runner, `instructions(agent)` the role text for AIs that have no agents of their own."""
        raise NotImplementedError

    def review(self, run, name, agent, model, cid, review_path, instructions, effort=None):
        """One independent review: returns the reviewer's text (the caller reads its VERDICT)."""
        raise NotImplementedError

    def ask(self, model, prompt, cwd=None):
        """One quick read-only question (no live output): the answer text, or None when it could not be reached."""
        raise NotImplementedError


class ClaudeCode(AI):
    native = True

    def call(self, run, role, agent, model, prompt, mode, instructions, effort=None):
        return run.claude(role, agent, prompt, model=model, **_eff(effort))

    def review(self, run, name, agent, model, cid, review_path, instructions, effort=None):
        note = f"Review input (card without plan/log, diff, CI tail): {review_path.as_posix()}."
        return run.claude(name, agent, f"Evaluate card {cid}. {note} Follow your agent instructions.", model=model, **_eff(effort))

    def ask(self, model, prompt, cwd=None):
        from . import suggest  # late: suggest.ask_claude is the one place that talks to `claude -p` (tests replace it)
        return suggest.ask_claude(prompt, cwd=cwd, model=model or "haiku")


class GenericCLI(AI):
    def call(self, run, role, agent, model, prompt, mode, instructions, effort=None):
        return run.provider(role, self.id, model, instructions(agent) + prompt, mode, **_eff(effort))

    def review(self, run, name, agent, model, cid, review_path, instructions, effort=None):
        text = review_path.read_text(encoding="utf-8", errors="replace")[:60000]       # the review input is INLINED: this AI may not be able to read files
        return run.provider(name, self.id, model, instructions(agent) + f"Evaluate card {cid}. Do not run commands or edit files.\n\n# REVIEW INPUT\n{text}", "read",
                            **_eff(effort))

    def ask(self, model, prompt, cwd=None):
        return providers.run_text(self.spec, model, prompt, "read", cwd=cwd)


def registry(cfg=None):
    """{id: AI} for the presets and the providers of this config."""
    return {pid: (ClaudeCode if spec.get("native") else GenericCLI)(spec) for pid, spec in providers.registry(cfg).items()}

