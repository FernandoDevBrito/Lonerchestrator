"""Trust for the one thing the orchestrator runs through a shell: the project's `ci` command (.orchestrator/config.json).
A repository you cloned could ship a config whose `ci` does anything, so each project must be approved once, per exact command."""
import hashlib
import json
from pathlib import Path

from .usage import _write_atomic, home


def _file():
    return home() / "trusted.json"


def _load():
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _key(project):
    return str(Path(project).resolve())


def _digest(cfg):
    return hashlib.sha256(cfg["ci"].encode("utf-8")).hexdigest()


def is_trusted(project, cfg):
    return _load().get(_key(project)) == _digest(cfg)


def trust(project, cfg):
    data = _load()
    data[_key(project)] = _digest(cfg)
    _write_atomic(_file(), data)
