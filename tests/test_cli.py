from test_anyai import mine, records  # noqa: F401  (the fixture: config with a fake third-party AI in every role)

from orch.cli import main


def test_init_new_and_dry_run(tmp_path, capsys):
    from orch import folder
    (tmp_path / "keep.txt").write_text("x")
    assert main(["-C", str(tmp_path), "init"]) == 0
    home = folder.of(tmp_path)
    assert (home / "config.json").exists() and (home / "board" / "backlog").is_dir() and (home / "context" / "project.md").exists()
    assert (home / "agents" / "splitter.md").exists() and (home / "rules.md").exists() and (home / "ci.sh").exists()
    assert [f.name for f in tmp_path.iterdir()] == ["keep.txt"]                    # the project gets nothing
    # idempotent: existing files are kept
    (home / "rules.md").write_text("mine")
    assert main(["-C", str(tmp_path), "init"]) == 0
    assert (home / "rules.md").read_text() == "mine"
    # new card is numbered and dry-run validates it (template placeholders = invalid)
    assert main(["-C", str(tmp_path), "new", "Do the thing", "--area", "both"]) == 0
    assert (home / "board" / "backlog" / "001-do-the-thing.md").exists()
    main(["-C", str(tmp_path), "run", "--dry-run"])
    assert "INVALID" in capsys.readouterr().out


def test_bare_command_opens_live_for_this_folder(tmp_path, monkeypatch):
    from orch import cli
    seen = {}
    monkeypatch.setitem(cli.COMMANDS, "live", lambda a, project: seen.update(cmd=a.cmd, project=project) or 0)
    assert main(["-C", str(tmp_path)]) == 0
    assert seen == {"cmd": "live", "project": tmp_path.resolve()}


def test_live_refuses_uninitialized_folder(tmp_path, capsys, monkeypatch):
    from orch import cli
    monkeypatch.setattr(cli.shutil, "which", lambda name: "wt")
    assert main(["-C", str(tmp_path), "live"]) == 1
    assert "lonerchestrator init" in capsys.readouterr().out


def test_run_commits_nothing_of_its_own_and_works_around_your_changes(project, capsys, monkeypatch):
    """No clean tree needed: `run` leaves your changes as they are and builds cards in worktrees while you have them. It has no files of its own to commit."""
    import subprocess

    from conftest import sh

    from orch import cli, config, parallel, trust
    trust.trust(project, config.load(project))
    used = []

    class Fake:
        def __init__(self, *a, **k):
            used.append(type(self).__name__)

        def preflight(self):
            pass

        def run(self, only=None):
            return 0
    monkeypatch.setattr(parallel, "Parallel", type("Parallel", (Fake,), {}))
    monkeypatch.setattr(cli, "Pipeline", type("Pipeline", (Fake,), {}))
    git = lambda *a: subprocess.run(["git", *a], cwd=project, capture_output=True, text=True, check=True).stdout   # noqa: E731
    head = git("rev-parse", "HEAD")
    (project / "app.py").write_text("mine = 1\n")                                   # yours: untracked
    (project / "staged.py").write_text("s = 1\n")
    sh(project, "git", "add", "staged.py")                                           # yours: staged
    assert main(["-C", str(project), "run"]) == 0 and used == ["Parallel"]
    assert git("rev-parse", "HEAD") == head                                          # no commit of its own
    assert sorted(git("status", "--porcelain").splitlines()) == ["?? app.py", "A  staged.py"]
    assert "they stay as they are" in capsys.readouterr().out
    sh(project, "git", "add", "-A")
    sh(project, "git", "commit", "-qm", "mine")
    assert main(["-C", str(project), "run"]) == 0 and used[-1] == "Pipeline"        # nothing of yours uncommitted: in place, as before
    sh(project, "git", "checkout", "-q", "-b", "side")
    (project / "app.py").write_text("mine = 2\n")
    assert main(["-C", str(project), "run"]) == 1 and "switch to main" in capsys.readouterr().out


def test_a_fresh_init_runs_while_you_have_work_in_progress(project, mine):  # noqa: F811
    """The everyday case: `init` just ran and you have work of your own in progress. The card still lands, and the project only gets the card's code."""
    import subprocess

    from conftest import add_card, home

    from orch import config, trust
    from orch.board import Board
    cfg, _ = mine
    assert main(["-C", str(project), "init"]) == 0
    config.write_raw(project, {**config.read_raw(project), **{k: cfg[k] for k in ("ci", "providers", "roles", "reviewers")}})
    trust.trust(project, config.load(project))
    (home(project) / "context" / "project.md").write_text("# Project\nA small demo.\n")
    (project / "app.py").write_text("mine = 1\n")
    add_card(project, "001-a")
    assert main(["-C", str(project), "run"]) == 0
    assert [c.id for c in Board(project).cards("done")] == ["001-a"] and (project / "001-a.py").exists()
    assert subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True).stdout.splitlines() == ["?? app.py"]


def test_run_without_any_commit_says_how_to_make_the_first(tmp_path, capsys):
    from conftest import sh

    from orch import config, trust
    sh(tmp_path, "git", "init", "-q", "-b", "main")
    trust.trust(tmp_path, config.load(tmp_path))
    assert main(["-C", str(tmp_path), "run"]) == 1 and "make the first commit" in capsys.readouterr().out


def test_an_old_project_moves_into_its_folder_and_keeps_what_is_yours(project):
    """Older versions kept the orchestrator's files in the project: they move to the folder, the user's files stay, the approval holds."""
    import json

    from conftest import CARD, home

    from orch import config, folder, trust
    p, old = project, {"ci": "bash scripts/ci.sh", "split": False}
    (p / ".orchestrator" / "runs" / "r1").mkdir(parents=True)
    (p / ".orchestrator" / "runs" / "r1" / "events.jsonl").write_text("{}\n")
    (p / ".orchestrator" / "config.json").write_text(json.dumps(old))
    (p / "board" / "backlog").mkdir(parents=True)
    (p / "board" / "backlog" / ".gitkeep").write_text("")
    (p / "board" / "backlog" / "001-a.md").write_text(CARD)
    (p / "board" / "_log.md").write_text("| log |\n")
    (p / "board" / "_TEMPLATE.md").write_text('area: backend   # or any key of "agents" in .orchestrator/config.json\n- [ ] <e.g. `bash scripts/ci.sh` passes>\n')
    (p / "context").mkdir()
    (p / "context" / "project.md").write_text("# Project\nmine\n")
    (p / "memory").mkdir()
    (p / "memory" / "backend.md").write_text("# lessons\n")
    (p / "scripts").mkdir()
    (p / "scripts" / "ci.sh").write_text('#!/usr/bin/env bash\n# CI gate for this project\ncd "$(dirname "$0")/.."\nexit 0\n')
    (p / "scripts" / "deploy.sh").write_text("echo mine\n")                                          # yours
    (p / "CLAUDE.md").write_text("# Orchestrator rules + project context\n")
    (p / ".claude" / "agents").mkdir(parents=True)
    (p / ".claude" / "agents" / "backend.md").write_text("---\nname: backend\n---\nRead `memory/backend.md`.\nRESULT: DONE\n")
    (p / ".claude" / "agents" / "data-eng.md").write_text("---\nname: data-eng\n---\nRun `bash scripts/ci.sh`, read `context/project.md`.\nRESULT: DONE\n")
    (p / ".claude" / "agents" / "helper.md").write_text("---\nname: helper\n---\nA Claude Code agent of yours.\n")      # yours
    (p / ".gitignore").write_bytes(b"__pycache__/\n# orchestrator runtime state\nboard/*/*.md\n.orchestrator/runs/\nnode_modules/\n")
    trust.trust(p, config.merged(old))
    moved = folder.migrate(p, say=lambda _: None)
    h = home(p)
    assert (h / "board" / "backlog" / "001-a.md").read_text() == CARD and (h / "log.md").read_text() == "| log |\n"
    assert (h / "runs" / "r1" / "events.jsonl").is_file() and (h / "context" / "project.md").read_text() == "# Project\nmine\n"
    assert (h / "memory" / "backend.md").read_text() == "# lessons\n"
    assert (h / "ci.sh").read_bytes() == b"#!/usr/bin/env bash\n# CI gate for this project\nexit 0\n"  # runs where it is started; LF for bash
    assert (h / "board" / "_TEMPLATE.md").read_text() == 'area: backend   # or any key of "agents" in the config\n- [ ] <e.g. CI passes>\n'
    assert json.loads((h / "config.json").read_text()) == {"split": False}                          # the old default CI command: the folder's script
    assert trust.is_trusted(p, config.load(p))                                                       # approved before: still approved
    assert (h / "old-setup" / "CLAUDE.md").is_file() and (h / "old-setup" / ".claude" / "agents" / "backend.md").is_file()
    assert (h / "agents" / "backend.md").read_text() == (folder.TEMPLATES / "agents" / "backend.md").read_text()      # the new template
    assert (h / "agents" / "data-eng.md").read_text().count("{ci}`, read `{folder}/context/project.md`") == 1             # your agent, pointed at the folder
    left = sorted(f.relative_to(p).as_posix() for f in p.rglob("*") if f.is_file() and ".git" not in f.relative_to(p).parts)
    assert left == [".claude/agents/helper.md", ".gitignore", "scripts/deploy.sh"]
    assert (p / ".gitignore").read_bytes() == b"__pycache__/\nnode_modules/\n"                     # its line endings kept
    assert "board/backlog/001-a.md" in moved and folder.migrate(p) == []                             # once


def test_a_project_that_moved_gets_its_folder_back(project, tmp_path):
    """Renamed, moved to another drive, or cloned again after it was lost: the same repository (same first commit) in a new place gets its
    folder back on the first command, cards and approval included. A clone whose original is still in its place starts a folder of its own."""
    import json
    import shutil

    from conftest import add_card, home, sh

    from orch import config, folder, trust
    from orch.board import Board
    assert main(["-C", str(project), "init"]) == 0
    add_card(project, "001-a")
    before = home(project)
    assert json.loads((before / "project.json").read_text())["first_commits"]
    clone = tmp_path / "clone"
    sh(tmp_path, "git", "clone", "-q", str(project), str(clone))
    main(["-C", str(clone), "status"])
    assert not folder.exists(clone) and before.is_dir()                                     # never shared with the original
    moved = tmp_path / "elsewhere" / "proj"
    moved.parent.mkdir()
    shutil.move(str(project), str(moved))
    assert main(["-C", str(moved), "status"]) == 0
    assert not before.exists() and [c.id for c in Board(moved).cards("backlog")] == ["001-a"]
    assert trust.is_trusted(moved, config.load(moved))
    assert json.loads((home(moved) / "project.json").read_text())["path"] == str(moved.resolve())
    assert folder.locate(clone) is None and not folder.exists(clone)                       # taken once, by the first to ask


def test_every_command_function_is_in_the_command_table():
    import inspect

    from orch import cli
    funcs = {n[4:] for n, f in inspect.getmembers(cli, inspect.isfunction) if n.startswith("cmd_")}
    assert set(cli.COMMANDS) == funcs and all(callable(f) for f in cli.COMMANDS.values())
