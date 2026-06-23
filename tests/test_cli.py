import json, subprocess, io, contextlib
from pathlib import Path


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("baseline")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, env=env, check=True)
    return repo


def test_cli_goal_check_no_rounds_exits_1(tmp_path):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    try:
        main(["goal-check", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "should have exited 1"
    except SystemExit as e:
        assert e.code == 1


def test_cli_apply_variant_prints_worktree_and_harness(tmp_path):
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    data = json.loads(buf.getvalue())
    assert "worktree" in data and Path(data["worktree"]).exists()
    assert data["harness"] == ["CLAUDE.md"]
    remove_worktree(data["worktree"])
    assert (repo / "CLAUDE.md").read_text() == "baseline"


def test_cli_snapshot_copies_harness_from_worktree(tmp_path):
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    # stage a worktree, edit the harness there, then snapshot it
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    wt = json.loads(buf.getvalue())["worktree"]
    Path(wt, "CLAUDE.md").write_text("round1-edited")
    dest = tmp_path / "snap"
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        main(["snapshot", "--eval", str(ev), "--worktree", wt, "--dest", str(dest), "--base", str(repo)])
    out = json.loads(buf2.getvalue())
    assert out["files"] == ["CLAUDE.md"]
    assert (dest / "CLAUDE.md").read_text() == "round1-edited"
    remove_worktree(wt)
