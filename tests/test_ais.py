import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from orch import aisetup, catalog, cli, term
from orch.cli import main

ROOT = Path(__file__).resolve().parent.parent
POSIX_AGY = ["bash", "-c", "curl -fsSL https://antigravity.google/cli/install.sh | bash"]
WIN_AGY = ["powershell", "-NoProfile", "-Command", "irm https://antigravity.google/cli/install.ps1 | iex"]


class Fake:
    """Pretend machine: `have` is what is installed; a fake installer 'installs' the CLI it is asked for."""

    def __init__(self, have=(), answers=(), rc=0, on_path_after=True):
        self.have, self.answers, self.rc, self.after = set(have), list(answers), rc, on_path_after
        self.ran, self.asked, self.lines = [], [], []

    def which(self, exe):
        return f"/bin/{exe}" if exe in self.have else None

    def ask(self, prompt):
        self.asked.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def run(self, argv, check=False):
        self.ran.append(argv)
        if not self.rc and self.after:
            self.have.add("agy" if "antigravity" in argv[-1] else "claude")
        return SimpleNamespace(returncode=self.rc)

    def go(self, **kw):
        kw.setdefault("system", "posix")
        rc = aisetup.run_setup(ask=self.ask, out=self.lines.append, which=self.which, run=self.run, **kw)
        return rc, "\n".join(self.lines)


def no_home_dirs(monkeypatch, tmp_path):
    """Keep find() from seeing the real ~/.local/bin or %LOCALAPPDATA%."""
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    no_home_dirs(monkeypatch, tmp_path)


# ---- the menu --------------------------------------------------------------------------------------------------
def test_lists_installed_and_missing_and_does_not_ask_when_nothing_is_missing():
    f = Fake(have={"claude", "agy"})
    rc, out = f.go()
    assert rc == 0 and f.asked == [] and f.ran == []
    assert "[x] Claude Code" in out and "[x] Antigravity CLI" in out and "installed" in out


def test_offers_only_the_missing_one_and_runs_its_official_installer_after_yes():
    f = Fake(have={"claude"}, answers=["1", "y"])
    rc, out = f.go()
    assert rc == 0 and f.ran == [POSIX_AGY]
    assert "[ ] Antigravity CLI" in out and "1) Antigravity CLI" in out
    assert "curl -fsSL https://antigravity.google/cli/install.sh | bash" in out          # the command was shown before running
    assert "installed: /bin/agy" in out and "sign in with a Google account" in out


def test_windows_uses_the_powershell_installer():
    f = Fake(have={"claude"}, answers=["1", "y"])
    f.go(system="windows")
    assert f.ran == [WIN_AGY]


def test_a_installs_all_missing_in_order():
    f = Fake(answers=["a", "y", "y"])
    rc, out = f.go()
    assert [r[-1].split("/")[2] for r in f.ran] == ["claude.ai", "antigravity.google"] and rc == 0
    assert "run `claude` once" in out


def test_nothing_runs_without_a_yes():
    for answers in ([""], ["1", "n"], ["1", ""], ["x"], []):          # skip, decline, empty confirmation, garbage, EOF (no terminal)
        f = Fake(have={"claude"}, answers=answers)
        rc, out = f.go()
        assert f.ran == [] and rc == 0, answers


def test_numbers_are_deduplicated_and_out_of_range_ignored():
    f = Fake(answers=["2 2 9 0", "y"])
    f.go()
    assert len(f.ran) == 1 and "antigravity" in f.ran[0][-1]


def test_failed_installer_reports_the_manual_steps_and_continues():
    f = Fake(answers=["a", "y", "y"], rc=1)
    rc, out = f.go()
    assert rc == 1 and len(f.ran) == 2 and out.count("the installer failed") == 2
    assert "https://code.claude.com/docs/en/setup" in out and "https://antigravity.google/docs" in out


def test_fresh_install_not_yet_on_path_tells_you_to_open_a_new_terminal():
    f = Fake(have={"claude"}, answers=["1", "y"], on_path_after=False)
    rc, out = f.go()
    assert rc == 0 and "Open a NEW terminal" in out


def test_installer_folder_is_found_even_when_not_on_path(tmp_path):
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    (tmp_path / ".local" / "bin" / "claude").write_text("")
    entry = next(e for e in catalog.AIS if e["id"] == "claude")
    assert aisetup.find(entry, which=lambda _: None, system="posix") == str(tmp_path / ".local" / "bin" / "claude")
    agy = next(e for e in catalog.AIS if e["id"] == "agy")
    (tmp_path / "local" / "agy" / "bin").mkdir(parents=True)
    (tmp_path / "local" / "agy" / "bin" / "agy.exe").write_text("")
    assert aisetup.find(agy, which=lambda _: None, system="windows").endswith("agy.exe")
    assert aisetup.find(agy, which=lambda _: None, system="posix") is None            # that folder is Windows-only


# ---- non-interactive use ---------------------------------------------------------------------------------------------
def test_install_flag_runs_without_asking_and_skips_what_is_already_there():
    f = Fake(have={"claude"})
    rc, out = f.go(only=["claude", "agy"], assume_yes=True, interactive=False)
    assert rc == 0 and f.asked == [] and f.ran == [POSIX_AGY]
    assert "Already installed, nothing to do: claude" in out


def test_install_all_and_unknown_names():
    f = Fake()
    assert f.go(only=["all"], assume_yes=True)[0] == 0 and len(f.ran) == 2
    g = Fake()
    rc, out = g.go(only=["claude", "gpt"], assume_yes=True)
    assert rc == 2 and g.ran == [] and "Unknown AI: gpt" in out


def test_install_flag_still_asks_unless_yes():
    f = Fake(answers=["n"])
    f.go(only=["agy"])
    assert f.ran == [] and f.asked == ["  Run it? [y/N] "]


def test_without_a_terminal_it_only_lists_and_says_how_to_install():
    f = Fake(have={"claude"})
    rc, out = f.go(interactive=False)
    assert rc == 0 and f.asked == [] and f.ran == [] and "lonerchestrator ais --install" in out


# ---- the CLI wiring ------------------------------------------------------------------------------------------------------
def test_cli_passes_the_flags_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.aisetup, "run_setup", lambda **kw: seen.update(kw) or 0)
    assert main(["ais", "--install", "Claude, agy", "--yes"]) == 0
    assert seen == {"assume_yes": True, "only": ["claude", "agy"], "interactive": False}       # pytest has no terminal
    seen.clear()
    main(["ais"])
    assert seen["only"] is None and seen["assume_yes"] is False


def test_cli_ais_lists_and_rejects_unknown(capsys):
    assert main(["ais"]) == 0
    assert "AIs on this computer" in capsys.readouterr().out
    assert main(["ais", "--install", "nope", "--yes"]) == 2


# ---- the catalog is the only place commands come from ----------------------------------------------------------------------
def test_catalog_commands_are_the_vendors_own_and_documented_in_requirements():
    readme = (ROOT / "requirements" / "README.md").read_text(encoding="utf-8").replace("\\|", "|")
    hosts = {"claude": "https://claude.ai/install.", "agy": "https://antigravity.google/cli/install."}
    for e in catalog.AIS:
        assert {"id", "name", "exe", "required", "why", "url", "install", "login"} <= set(e)
        for system, cmd in e["install"].items():
            assert hosts[e["id"]] in cmd, f"{e['id']}/{system}: an unvetted installer URL"
            assert cmd in readme, f"{cmd} is missing from requirements/README.md"
        assert e["name"] in readme
    assert next(e for e in catalog.AIS if e["id"] == "claude")["required"] is True


def test_requirements_files():
    runtime = (ROOT / "requirements" / "runtime.txt").read_text(encoding="utf-8")
    assert [ln for ln in runtime.splitlines() if ln.strip() and not ln.startswith("#")] == []        # no Python dependencies
    dev = [ln for ln in (ROOT / "requirements" / "dev.txt").read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    assert {re.split(r"[<>=]", ln)[0] for ln in dev} >= {"pytest", "ruff", "build"}
    assert all(re.fullmatch(r"[a-z0-9_.-]+>=[0-9.]+", ln) for ln in dev)


# ---- the installers offer the AIs ----------------------------------------------------------------------------------------------
def test_installers_know_the_with_option():
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_bytes().decode("utf-8")
    assert '"-With"' in ps1 and "LONERCHESTRATOR_WITH" in ps1 and "ais --install" in ps1
    assert "--with)" in sh and "LONERCHESTRATOR_WITH" in sh and "ais --install" in sh and "/dev/tty" in sh


def _usable_bash():
    b = term.real_bash()
    return b if b and "windowsapps" not in b.lower() else None


@pytest.mark.skipif(_usable_bash() is None, reason="no usable bash")
@pytest.mark.parametrize("extra,expected", [(["--with", "claude,agy"], "lonerchestrator ais --install claude,agy --yes"), ([], "lonerchestrator ais   (shows")])
def test_install_sh_dry_run_shows_the_ai_step(tmp_path, extra, expected):
    r = subprocess.run([_usable_bash(), str(ROOT / "install.sh"), "--dry-run", "--manager", "pip", *extra],
                       cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    assert r.returncode == 0 and expected in r.stdout, r.stdout + r.stderr
    assert list(tmp_path.iterdir()) == []
