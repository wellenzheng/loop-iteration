import subprocess
from pathlib import Path
import importlib.util

def _load_run_case():
    p = Path("adapters/toy/run_case.py").resolve()
    spec = importlib.util.spec_from_file_location("toy_run_case", p)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _repo_with_agent(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "agent_files").mkdir()
    (repo / "agent_files" / "SKILL.md").write_text("answer in one word")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, env=env, check=True)
    return repo


def test_run_case_returns_result_shape_with_fake_agent(tmp_path, monkeypatch):
    from loop_iter.adapter import apply_variant, remove_worktree
    repo = _repo_with_agent(tmp_path)
    wt = apply_variant(str(repo), "HEAD", "agent_files")
    mod = _load_run_case()

    fake_agent = tmp_path / "fake_agent.sh"
    fake_agent.write_text("#!/bin/sh\necho \"$(cat)\" | tr a-z A-Z\n")
    fake_agent.chmod(0o755)
    monkeypatch.setattr(mod, "AGENT_CMD", [str(fake_agent)])

    result = mod.run_case(
        case={"id": "c1", "query": "hello", "expected": None},
        worktree=wt, agent_subdir="agent_files",
    )
    assert result["case_id"] == "c1"
    assert result["output"].strip() == "HELLO"
    assert result["error"] is None
    remove_worktree(wt)
