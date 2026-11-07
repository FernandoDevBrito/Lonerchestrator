from orch.cli import main


def test_init_new_and_dry_run(tmp_path, capsys):
    (tmp_path / "keep.txt").write_text("x")
    assert main(["-C", str(tmp_path), "init"]) == 0
    assert (tmp_path / ".orchestrator" / "config.json").exists()
    assert (tmp_path / "board" / "backlog" / ".gitkeep").exists()
    gi = (tmp_path / ".gitignore").read_text()
    assert "board/*/*.md" in gi
    # idempotent: existing files are kept
    (tmp_path / "CLAUDE.md").write_text("mine")
    assert main(["-C", str(tmp_path), "init"]) == 0
    assert (tmp_path / "CLAUDE.md").read_text() == "mine"
    # new card is numbered and dry-run validates it (template placeholders = invalid)
    assert main(["-C", str(tmp_path), "new", "Do the thing", "--area", "both"]) == 0
    assert (tmp_path / "board" / "backlog" / "001-do-the-thing.md").exists()
    main(["-C", str(tmp_path), "run", "--dry-run"])
    assert "INVALID" in capsys.readouterr().out
