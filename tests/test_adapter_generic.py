from loop_iter.adapter_generic import resolve_harness


def test_resolve_harness_default_convention(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude/skills/foo").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("x")
    (repo / ".claude/skills/foo/SKILL.md").write_text("y")
    eval_dir = tmp_path / "eval"; eval_dir.mkdir()
    (eval_dir / "goal.yaml").write_text("threshold: 0.8\n")  # no harness key
    paths = resolve_harness(str(eval_dir), str(repo))
    assert "CLAUDE.md" in paths
    assert any(p.endswith("foo/SKILL.md") for p in paths)


def test_resolve_harness_override_replaces_default(tmp_path):
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("x")
    (repo / "prompts/p.md").write_text("y")
    eval_dir = tmp_path / "eval"; eval_dir.mkdir()
    (eval_dir / "goal.yaml").write_text("harness:\n  - prompts/**/*.md\n")
    paths = resolve_harness(str(eval_dir), str(repo))
    assert "CLAUDE.md" not in paths            # default replaced
    assert any(p.endswith("prompts/p.md") for p in paths)


def test_resolve_harness_skips_absent_default_paths(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("x")       # no AGENTS.md, no .claude/
    eval_dir = tmp_path / "eval"; eval_dir.mkdir()
    (eval_dir / "goal.yaml").write_text("threshold: 0.8\n")
    paths = resolve_harness(str(eval_dir), str(repo))
    assert paths == ["CLAUDE.md"]
