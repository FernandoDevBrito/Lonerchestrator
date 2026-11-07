"""Local multi-agent orchestrator: board of cards -> plan -> build -> guardrails -> CI -> independent review -> merge."""
try:
    from importlib.metadata import version as _version

    __version__ = _version("lonerchestrator")
except Exception:          # running from a source checkout that was never installed
    __version__ = "dev"
