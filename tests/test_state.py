from loop_iter.state import RunPaths, write_scores, load_scores, write_progress, append_round

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
