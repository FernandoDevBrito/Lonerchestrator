
import pytest

from orch import term

ARGV = ["python", "-m", "orch", "tui"]


def has(*names):
    return lambda n: n if n in names else None


def test_parse_keys_arrows_pages_and_plain():
    assert term.parse_keys("\x1b[A\x1b[B\x1b[C\x1b[D") == ["up", "down", "right", "left"]
    assert term.parse_keys("\x1b[5~\x1b[6~") == ["pgup", "pgdn"]
    assert term.parse_keys("\x1bOA") == ["up"]                       # application-cursor mode
    assert term.parse_keys("\x1b[1;5C") == ["right"]                 # ctrl+arrow still maps
    assert term.parse_keys("r\tq1") == ["r", "\t", "q", "1"]
    assert term.parse_keys("\x1b[3~") == [""]                        # unknown sequences are swallowed, not typed


def test_window_command_windows_uses_wt_with_size():
    cmd = term.window_command("Windows", has("wt"), ARGV, "t", "C:/p", 120, 34)
    assert cmd[:3] == ["wt", "--size", "120,34"] and cmd[-5:] == ["cmd", "/k", *ARGV][-5:]
    assert term.window_command("Windows", has(), ARGV, "t", "C:/p", 120, 34) is None


def test_window_command_macos_quotes_the_path():
    cmd = term.window_command("Darwin", has("osascript"), ARGV, "t", "/Users/me/my proj", 120, 34)
    script = cmd[2]
    assert cmd[0] == "osascript" and "do script" in script and "'/Users/me/my proj'" in script and "exec python -m orch tui" in script
    assert term.window_command("Darwin", has(), ARGV, "t", "/x", 120, 34) is None


@pytest.mark.parametrize("name,flag", [("gnome-terminal", "--geometry=120x34"), ("xterm", "120x34"), ("kitty", "initial_window_width=120c"),
                                       ("alacritty", "window.dimensions.columns=120"), ("xfce4-terminal", "--geometry=120x34")])
def test_window_command_linux_picks_first_available_terminal(name, flag):
    cmd = term.window_command("Linux", has(name), ARGV, "t", "/p", 120, 34, env={"DISPLAY": ":0"})
    assert cmd[0] == name and any(flag in part for part in cmd) and cmd[-4:] == ARGV


def test_window_command_linux_headless_or_no_terminal():
    assert term.window_command("Linux", has("xterm"), ARGV, "t", "/p", 120, 34, env={}) is None          # ssh / no display
    assert term.window_command("Linux", has(), ARGV, "t", "/p", 120, 34, env={"WAYLAND_DISPLAY": "w"}) is None


def test_spawn_and_kill_tree(tmp_path):
    import sys
    import time
    out = open(tmp_path / "o.txt", "w")  # noqa: SIM115
    p = term.spawn([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), None, out)
    assert p.poll() is None
    term.kill_tree(p)
    for _ in range(50):
        if p.poll() is not None:
            break
        time.sleep(0.1)
    out.close()
    assert p.poll() is not None
