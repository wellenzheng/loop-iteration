import subprocess
from pathlib import Path
from loop_iter.adapter import apply_variant, remove_worktree, snapshot_variant


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent_files").mkdir()
    (repo / "agent_files" / "SKILL.md").write_text("baseline")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, env=env, check=True)
    return repo


def test_apply_variant_creates_worktree_and_source_untouched(tmp_path):
    repo = _repo(tmp_path)
    wt = apply_variant(repo_root=str(repo), baseline_ref="HEAD", agent_subdir="agent_files")
    assert Path(wt, "agent_files", "SKILL.md").read_text() == "baseline"
    Path(wt, "agent_files", "SKILL.md").write_text("edited")
    assert (repo / "agent_files" / "SKILL.md").read_text() == "baseline"
    remove_worktree(wt)


def test_snapshot_variant_copies_subdir(tmp_path):
    repo = _repo(tmp_path)
    wt = apply_variant(str(repo), "HEAD", "agent_files")
    Path(wt, "agent_files", "SKILL.md").write_text("round1")
    dest = tmp_path / "snap"
    snapshot_variant(wt, "agent_files", str(dest))
    assert (dest / "SKILL.md").read_text() == "round1"
    remove_worktree(wt)


def test_remove_worktree_cleans_up(tmp_path):
    repo = _repo(tmp_path)
    wt = apply_variant(str(repo), "HEAD", "agent_files")
    remove_worktree(wt)
    assert not Path(wt).exists()
