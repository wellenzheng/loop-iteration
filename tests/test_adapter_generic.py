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


from loop_iter.adapter_generic import load_run_case, run_case_default, build_agent_cmd, snapshot_harness


def test_load_run_case_none_when_absent(tmp_path):
    assert load_run_case(str(tmp_path)) is None


def test_load_run_case_loads_when_present(tmp_path):
    (tmp_path / "run_case.py").write_text(
        "def run_case(case, worktree, harness):\n"
        "    return {'case_id': case['id'], 'output': 'CUSTOM', 'trace': {}, 'error': None}\n"
    )
    fn = load_run_case(str(tmp_path))
    assert fn is not None
    r = fn({"id": "c1", "query": "q", "expected": None}, "/tmp", [])
    assert r["output"] == "CUSTOM"


def test_build_agent_cmd_defaults_and_overrides():
    assert build_agent_cmd({}) == ["claude", "-p", "--permission-mode", "bypassPermissions"]
    cmd = build_agent_cmd({"model": "claude-sonnet-4-6", "permission_mode": "acceptEdits", "extra_args": ["--foo"]})
    assert cmd == ["claude", "-p", "--permission-mode", "acceptEdits", "--model", "claude-sonnet-4-6", "--foo"]


def test_run_case_default_with_fake_agent(tmp_path, monkeypatch):
    import loop_iter.adapter_generic as ag
    fake = tmp_path / "fake.sh"
    fake.write_text("#!/bin/sh\necho \"$(cat)\" | tr a-z A-Z\n")
    fake.chmod(0o755)
    monkeypatch.setattr(ag, "build_agent_cmd", lambda config: [str(fake)])
    r = ag.run_case_default({"id": "c1", "query": "hi", "expected": None}, str(tmp_path), {})
    assert r["case_id"] == "c1"
    assert r["output"].strip() == "HI"
    assert r["error"] is None


def test_snapshot_harness_copies_listed_files(tmp_path):
    wt = tmp_path / "wt"; (wt / ".claude/skills/foo").mkdir(parents=True)
    (wt / "CLAUDE.md").write_text("root")
    (wt / ".claude/skills/foo/SKILL.md").write_text("skill")
    dest = tmp_path / "snap"
    snapshot_harness(str(wt), ["CLAUDE.md", ".claude/skills/foo/SKILL.md"], str(dest))
    assert (dest / "CLAUDE.md").read_text() == "root"
    assert (dest / ".claude/skills/foo/SKILL.md").read_text() == "skill"
