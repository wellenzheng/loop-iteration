import json
import pytest
from loop_iter.state import (
    RunPaths,
    write_scores,
    load_scores,
    write_progress,
    append_round,
    init_state,
    load_state,
    write_state,
    advance_phase,
)

def test_run_paths_layout(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="20260623_120000_abcd1234")
    assert rp.progress.name == "progress.md"
    assert rp.scores.name == "scores.json"
    assert rp.scores.parent.name == "20260623_120000_abcd1234"

def test_write_and_load_scores_roundtrip(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    scores = {"round": 1, "cases": [], "composite": 0.5,
              "gate_pass_rates": {}, "judge_means": {}}
    write_scores(rp, scores)
    assert load_scores(rp) == scores

def test_append_round_accumulates(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    append_round(rp, {"round": 1, "composite": 0.4, "gate_pass_rates": {"exact": 1.0}, "cases": [], "judge_means": {}})
    append_round(rp, {"round": 2, "composite": 0.8, "gate_pass_rates": {"exact": 1.0}, "cases": [], "judge_means": {}})
    data = load_scores(rp)
    assert data["rounds"][0]["composite"] == 0.4
    assert data["rounds"][1]["composite"] == 0.8
    assert data["best_round"] == 2

def test_write_progress_creates_file(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    write_progress(rp, "## Round 1\ncomposite 0.4")
    assert "Round 1" in rp.progress.read_text()

def test_run_dir_under_self_iterate_runs(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    assert rp.run_dir == tmp_path / ".self-iterate" / "runs" / "r1"
    assert rp.state_file == rp.run_dir / "state.json"
    assert rp.baseline_file == rp.run_dir / "baseline.json"
    assert rp.report_md == rp.run_dir / "report.md"
    assert rp.winner_diff == rp.run_dir / "winner.diff"

def test_init_state_writes_baseline_phase(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    st = init_state(rp, "mygoal", 5)
    assert st["phase"] == "baseline"
    assert st["round"] == 0
    assert st["max_rounds"] == 5
    assert st["met"] is False
    assert st["goal"] == "mygoal"
    assert load_state(rp) == st

def test_load_state_raises_when_absent(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    with pytest.raises(FileNotFoundError):
        load_state(rp)

def test_advance_phase_checks_expected_and_advances(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    init_state(rp, "g", 3)
    st = advance_phase(rp, "baseline", "maker", updates={"round": 1})
    assert st["phase"] == "maker"
    assert st["round"] == 1
    assert load_state(rp)["phase"] == "maker"

def test_advance_phase_refuses_wrong_expected(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    init_state(rp, "g", 3)
    with pytest.raises(RuntimeError, match="phase guard"):
        advance_phase(rp, "eval", "goalcheck")   # state is baseline, not eval

def test_state_file_probe_does_not_create_run_dir(tmp_path):
    from loop_iter.state import RunPaths
    rp = RunPaths(base=str(tmp_path), run_id="ghost")
    assert rp.state_file.exists() is False        # read-only probe
    assert rp.run_dir.exists() is False           # MUST NOT have created the dir
