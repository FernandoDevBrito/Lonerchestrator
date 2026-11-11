import re
import subprocess
from pathlib import Path

import pytest

from orch import __version__, cli, term
from orch.cli import main

ROOT = Path(__file__).resolve().parent.parent


# ---- --version and doctor ----------------------------------------------------------------------------------------
def test_version_flag(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.strip() == f"lonerchestrator {__version__}"


def fake_which(present):
    return lambda name: f"/bin/{name}" if name in present else None


def test_doctor_all_good_in_a_project(project, monkeypatch, capsys):
    from orch import config, folder
    config.write_raw(project, {"base": "main"})
    (folder.of(project) / "ci.sh").write_text("exit 0\n")                   # the default CI command needs its script
    monkeypatch.setattr(cli.shutil, "which", fake_which({"git", "claude", "agy", "bash"}))
    monkeypatch.setattr(cli.term, "real_bash", lambda: "/bin/bash")
    assert main(["-C", str(project), "doctor"]) == 0
    out = capsys.readouterr().out
    assert "[ ok ] git" in out and "[ ok ] claude" in out and "Git: base 'main'" in out
    assert f"its folder: {folder.of(project)}" in out


def test_doctor_reports_what_is_missing_and_how_to_fix_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", fake_which({"git"}))
    monkeypatch.setattr(cli.term, "real_bash", lambda: None)
    assert main(["-C", str(tmp_path), "doctor"]) == 1                       # claude is required
    out = capsys.readouterr().out
    assert "[ xx ] claude not found" in out and "lonerchestrator ais" in out and "code.claude.com" in out
    assert "[ !! ] agy not found" in out and "optional" in out               # agy is only a warning
    assert "no project in this folder" in out and "lonerchestrator init" in out


def test_doctor_flags_the_wsl_launcher_as_not_a_usable_bash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", fake_which({"git", "claude"}))
    monkeypatch.setattr(cli.term, "real_bash", lambda: r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\bash.exe")
    main(["-C", str(tmp_path), "doctor"])
    assert "WSL launcher" in capsys.readouterr().out


# ---- bash on Windows --------------------------------------------------------------------------------------------------
def test_ci_command_untouched_off_windows_or_without_bash(monkeypatch):
    monkeypatch.setattr(term, "WINDOWS", False)
    assert term.fix_ci_command("bash scripts/ci.sh") == "bash scripts/ci.sh"
    monkeypatch.setattr(term, "WINDOWS", True)
    assert term.fix_ci_command("pytest -q") == "pytest -q"                   # only commands that start with bash are rewritten


def test_windows_prefers_git_bash_over_the_wsl_launcher(tmp_path, monkeypatch):
    git_root = tmp_path / "Git"
    (git_root / "cmd").mkdir(parents=True)
    (git_root / "bin").mkdir()
    (git_root / "cmd" / "git.exe").write_text("")
    (git_root / "bin" / "bash.exe").write_text("")
    apps = str(tmp_path / "WindowsApps" / "bash.exe")
    table = {"bash": apps, "git": str(git_root / "cmd" / "git.exe")}
    monkeypatch.setattr(term, "WINDOWS", True)
    monkeypatch.setattr(term.shutil, "which", table.get)
    assert term.real_bash() == str(git_root / "bin" / "bash.exe")
    assert term.fix_ci_command("bash scripts/ci.sh") == f'"{git_root / "bin" / "bash.exe"}" scripts/ci.sh'
    table["git"] = None                                                      # no Git for Windows: nothing better to offer
    assert term.real_bash() == apps
    table["bash"] = r"C:\Program Files\Git\bin\bash.exe"                      # a normal bash is kept as is
    assert term.real_bash() == table["bash"]


# ---- the installers -----------------------------------------------------------------------------------------------------
def test_installers_point_at_the_repo_and_are_pipe_safe():
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_bytes().decode("utf-8")
    assert "https://github.com/FernandoDevBrito/lonerchestrator" in ps1 and "https://github.com/FernandoDevBrito/lonerchestrator" in sh
    code = [ln for ln in ps1.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert not code[0].lower().startswith("param"), "a param() block breaks `irm ... | iex`"
    assert "\r" not in sh, "install.sh must have LF line endings to run through `curl | bash`"
    assert sh.startswith("#!/usr/bin/env bash")
    assert all(ord(c) < 128 for c in ps1), "PowerShell 5.1 reads BOM-less files as ANSI: keep install.ps1 pure ASCII"
    assert "${edit[@]+" in sh, "empty-array expansion must work in bash 3.2 (macOS) with set -u"


def _usable_bash():
    b = term.real_bash()
    return b if b and "windowsapps" not in b.lower() else None


@pytest.mark.skipif(_usable_bash() is None, reason="no usable bash")
def test_install_sh_dry_run_changes_nothing_and_reports_the_plan(tmp_path):
    r = subprocess.run([_usable_bash(), str(ROOT / "install.sh"), "--dry-run", "--manager", "pip", "--ref", "v9.9.9"],
                       cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "dry run finished" in r.stdout and "@v9.9.9" in r.stdout and "[dry ]" in r.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(_usable_bash() is None, reason="no usable bash")
def test_install_sh_rejects_unknown_options(tmp_path):
    r = subprocess.run([_usable_bash(), str(ROOT / "install.sh"), "--nope"], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert r.returncode == 2 and "unknown option" in r.stdout


# ---- release plumbing --------------------------------------------------------------------------------------------------
def test_release_workflow_uses_trusted_publishing_only_in_the_publish_job():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert wf.count("id-token: write") == 1 and wf.index("id-token: write") > wf.index("publish:")
    assert "pypa/gh-action-pypi-publish@release/v1" in wf and 'tags: ["v*"]' in wf
    assert "password:" not in wf.lower() and "secrets." not in wf                  # no stored credentials


def test_package_metadata_is_ready_for_pypi():
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "\d+\.\d+\.\d+"$', toml, re.M)
    for key in ("Homepage", "Source", "Issues", "Changelog"):
        assert re.search(rf"^{key} = \"https://github.com/FernandoDevBrito/lonerchestrator", toml, re.M), key
    assert 'lonerchestrator = "orch.cli:main"' in toml and "authors" in toml
