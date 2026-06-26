"""End-to-end (cli-level) of the quality_target flow with a STUBBED quality-judge: case-run computes
no_overfit only -> quality-merge merges a stubbed sub-agent's LLM dims -> goal-check requires
quality >= quality_target. Validates the wiring (the quality-judge agent itself is LLM behavior,
covered by dogfooding)."""
import json, subprocess, io, contextlib
from loop_iter.cli import main
from loop_iter.state import RunPaths, init_state, load_state, load_scores


def _repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("baseline harness")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, env=env, check=True)
    return repo


def test_quality_target_flow_case_run_merge_goal_check(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text(
        "threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n"
        "quality_target: 8.0\nharness: [CLAUDE.md]\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q","expected":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("clarity / maintainability")
    rp = RunPaths(base=str(repo), run_id="qt")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "qt", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    # baseline: skip_llm -> provisional baseline_quality = no_overfit only (10.0)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "qt", "--base", str(repo)])
    assert load_state(rp)["baseline_quality"] == 10.0
    # stubbed quality-judge on baseline -> merge
    jp = rp.run_dir / "quality_judge_baseline.json"
    jp.write_text('{"dims": [{"dim": "clarity", "score": 9.0}, {"dim": "maintainability", "score": 9.0}], "maker_feedback": ""}')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "qt", "--base", str(repo),
              "--baseline", "--from", str(jp)])
    # baseline_quality = mean(no_overfit=10, clarity=9, maintainability=9) = 9.333
    assert abs(load_state(rp)["baseline_quality"] - (10 + 9 + 9) / 3) < 1e-6

    # round 1 at eval phase
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo), "--run-id", "qt", "--base", str(repo), "--round", "1"])
    # provisional round quality = no_overfit only (10.0)
    assert load_scores(rp)["rounds"][-1]["quality"] == 10.0
    # stubbed quality-judge on the variant -> merge (low quality: clarity 5, maintainability 5)
    jp2 = rp.run_dir / "quality_judge.json"
    jp2.write_text('{"dims": [{"dim": "clarity", "score": 5.0}, {"dim": "maintainability", "score": 5.0}], "maker_feedback": "trim section 2"}')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "qt", "--base", str(repo),
              "--round", "1", "--from", str(jp2)])
    # round quality = mean(10, 5, 5) = 6.667 < quality_target 8.0 -> met blocked -> loops
    assert abs(load_scores(rp)["rounds"][-1]["quality"] - (10 + 5 + 5) / 3) < 1e-6
    import pytest
    with pytest.raises(SystemExit) as ei:
        main(["goal-check", "--eval", str(ev), "--run-id", "qt", "--base", str(repo)])
    assert ei.value.code == 1   # not met (quality 6.667 < target 8.0)
    st = load_state(rp)
    assert st["phase"] == "maker" and st["round"] == 2   # loops to round 2
