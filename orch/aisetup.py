"""`lonerchestrator ais`: which AI CLIs are on this computer, and an offer to install the missing ones with their official installers.
Pure enough to test: `which`, `run`, `ask` and `system` are injected, so tests never execute a real installer."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .catalog import AIS, IDS


def _system():
    return "windows" if sys.platform == "win32" else "posix"


def command(entry, system=None):
    """(argv, text): how to run the entry's official installer here, and the text shown to the user."""
    system = system or _system()
    text = entry["install"][system]
    return (["powershell", "-NoProfile", "-Command", text] if system == "windows" else ["bash", "-c", text]), text


def find(entry, which=shutil.which, system=None):
    """Path of the CLI. A fresh install is often not on this session's PATH yet, so the installer's own folder is checked too."""
    found = which(entry["exe"])
    if found:
        return found
    dirs = list(entry["dirs"]) + (entry["win_dirs"] if (system or _system()) == "windows" else [])
    for d in dirs:
        d = re.sub(r"%(\w+)%", lambda m: os.environ.get(m.group(1), m.group(0)), d)      # %VAR% is only expanded by os.path on Windows
        base = Path(os.path.expanduser(os.path.expandvars(d)))
        for name in (entry["exe"], entry["exe"] + ".exe"):
            if (base / name).is_file():
                return str(base / name)
    return None


def _yes(answer):
    return answer.strip().lower() in ("y", "yes", "s", "sim")


def run_setup(ask=input, out=print, which=shutil.which, run=None, system=None, assume_yes=False, only=None, interactive=True):
    """Show the AI CLIs and install the missing ones the user picks. Returns 0, 1 when an installer failed, 2 for an unknown name."""
    run = run or subprocess.run
    system = system or _system()
    rows = [(e, find(e, which, system)) for e in AIS]
    out("\nAIs on this computer\n")
    for e, path in rows:
        state = f"installed   {path}" if path else f"missing     {e['why']}" + ("" if e["required"] else " (optional)")
        out(f"  [{'x' if path else ' '}] {e['name']:<16} {state}")
    missing = [e for e, path in rows if not path]

    if only is not None:
        ids = IDS if "all" in only else only
        unknown = [i for i in ids if i not in IDS]
        if unknown:
            out(f"\nUnknown AI: {', '.join(unknown)}. Known: {', '.join(IDS)}, all")
            return 2
        chosen = [e for e in missing if e["id"] in ids]
        done = [i for i in ids if i not in {e["id"] for e in missing}]
        if done:
            out(f"\nAlready installed, nothing to do: {', '.join(done)}")
    elif interactive and missing:
        out("\nInstall the missing ones now? Type their numbers (for example 1 2), a for all, or press Enter to skip.")
        for n, e in enumerate(missing, 1):
            out(f"  {n}) {e['name']}")
        try:
            answer = ask("  > ").strip().lower()
        except EOFError:
            answer = ""
        nums = [int(t) for t in answer.replace(",", " ").split() if t.isdigit() and 1 <= int(t) <= len(missing)]
        chosen = missing if answer == "a" else [missing[n - 1] for n in dict.fromkeys(nums)]
    else:
        if missing:
            out("\nTo install the missing ones:  lonerchestrator ais   (asks first)   or   lonerchestrator ais --install claude,agy")
        return 0

    failed = 0
    for e in chosen:
        argv, text = command(e, system)
        out(f"\n{e['name']}: the official installer ({e['url']})\n    {text}")
        if not assume_yes:
            try:
                go = _yes(ask("  Run it? [y/N] "))
            except EOFError:
                go = False
            if not go:
                out("  skipped")
                continue
        rc = run(argv, check=False).returncode
        if rc:
            out(f"  the installer failed (exit code {rc}). Follow the manual steps instead: {e['url']}")
            failed = 1
            continue
        path = find(e, which, system)
        out(f"  installed: {path}" if path else "  installed. Open a NEW terminal so PATH updates, then run `lonerchestrator doctor`")
        out(f"  next: {e['login']}")
    return failed
