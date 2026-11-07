"""Platform glue for Windows, macOS and Linux: keyboard input, process groups, opening a sized terminal window."""
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"

_ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left"}
_TILDE = {"5": "pgup", "6": "pgdn"}
_CSI = re.compile(r"\x1b[\[O]([0-9;]*)([A-Za-z~])")
WIN_KEYS = {"H": "up", "P": "down", "K": "left", "M": "right", "I": "pgup", "Q": "pgdn"}


def parse_keys(data):
    """Terminal bytes (as text) -> key names: 'up', 'down', 'left', 'right', 'pgup', 'pgdn' or the plain character."""
    out, i = [], 0
    while i < len(data):
        m = _CSI.match(data, i)
        if m:
            code, fin = m.groups()
            out.append(_ARROWS.get(fin) or (_TILDE.get(code.split(";")[0], "") if fin == "~" else ""))
            i = m.end()
        else:
            out.append(data[i])
            i += 1
    return out


def read_keys():
    """Non-blocking: every key pressed since the last call."""
    if WINDOWS:
        import msvcrt
        out = []
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            out.append(WIN_KEYS.get(msvcrt.getwch(), "") if ch in ("\x00", "\xe0") else ch)
        return out
    import select
    data = ""
    while select.select([sys.stdin], [], [], 0)[0]:
        chunk = os.read(sys.stdin.fileno(), 64)
        if not chunk:
            break
        data += chunk.decode("utf-8", "ignore")
    return parse_keys(data)


class RawTerminal:
    """cbreak mode on POSIX so single key presses arrive without Enter; restored on exit. No-op on Windows."""

    old = None

    def __enter__(self):
        if not WINDOWS and sys.stdin.isatty():
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        if self.old is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def spawn(cmd, cwd, env, out):
    """Background process in its own group/session so the whole tree can be stopped."""
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)


def kill_tree(proc):
    if proc.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def real_bash():
    """A bash that works. On Windows the first `bash` on PATH is often the WSL launcher (WindowsApps), which fails when no Linux distro
    is installed, so prefer the bash that ships with Git for Windows (next to git)."""
    found = shutil.which("bash")
    if not WINDOWS or not found or "windowsapps" not in found.lower():
        return found
    git = shutil.which("git")
    for parent in (Path(git).resolve().parents if git else []):
        cand = parent / "bin" / "bash.exe"
        if cand.is_file():
            return str(cand)
    return found


def fix_ci_command(cmd):
    """The default CI command starts with `bash`: on Windows run it with a bash that works (see real_bash)."""
    if WINDOWS and cmd.startswith("bash "):
        b = real_bash()
        if b:
            return f'"{b}" {cmd[5:]}'
    return cmd


def _applescript_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def window_command(system, which, argv, title, cwd, cols, rows, env=None):
    """Command line that opens `argv` in a NEW terminal window of cols x rows, or None when no suitable terminal is found.
    Pure (system/which/env are injected) so it can be tested on any OS.
    Terminals that ignore the geometry are fixed by the TUI itself (xterm resize sequence), see tui.fit_window."""
    env = os.environ if env is None else env
    if system == "Windows":
        if not which("wt"):
            return None
        return ["wt", "--size", f"{cols},{rows}", "-w", "new", "new-tab", "--title", title, "-d", cwd, "cmd", "/k", *argv]
    if system == "Darwin":
        if not which("osascript"):
            return None
        line = f"cd {shlex.quote(cwd)} && exec {shlex.join(argv)}"
        return ["osascript", "-e", f"tell application \"Terminal\" to do script {_applescript_str(line)}", "-e", 'tell application "Terminal" to activate']
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return None                                  # headless / ssh: no GUI terminal to open
    geo = f"{cols}x{rows}"
    table = [
        ("gnome-terminal", ["gnome-terminal", f"--geometry={geo}", "--title", title, "--", *argv]),
        ("xfce4-terminal", ["xfce4-terminal", f"--geometry={geo}", "--title", title, "-x", *argv]),
        ("kitty", ["kitty", "-o", f"initial_window_width={cols}c", "-o", f"initial_window_height={rows}c", "--title", title, *argv]),
        ("alacritty", ["alacritty", "-o", f"window.dimensions.columns={cols}", "-o", f"window.dimensions.lines={rows}", "-T", title, "-e", *argv]),
        ("konsole", ["konsole", "-e", *argv]),
        ("xterm", ["xterm", "-geometry", geo, "-T", title, "-e", *argv]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", *argv]),
    ]
    return next((cmd for name, cmd in table if which(name)), None)


def open_window(argv, title, cwd, cols, rows):
    """True when a terminal window was opened."""
    system = {"win32": "Windows", "darwin": "Darwin"}.get(sys.platform, "Linux")
    cmd = window_command(system, shutil.which, argv, title, cwd, cols, rows)
    if not cmd:
        return False
    subprocess.Popen(cmd, cwd=cwd)
    return True
