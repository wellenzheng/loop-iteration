import json
from pathlib import Path
from loop_iter.dashboard import build_state_payload


def test_payload_from_empty_run_dir(tmp_path):
    p = build_state_payload(tmp_path)
    assert p["phase"] is None
    assert p["rounds"] == []


def test_payload_merges_state_baseline_scores(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "phase": "done", "round": 2, "max_rounds": 3, "met": True,
        "baseline_composite": 0.75, "baseline_quality": 5.0,
        "best": {"round": 2, "composite": 1.0, "worktree": None},
        "goal": "one-word", "run_id": "r1"}))
    (tmp_path / "baseline.json").write_text(json.dumps({
        "composite": 0.75, "gate_pass_rates": {"is_one_word": 0.5}, "quality": 5.0,
        "quality_dims": [{"dim": "no_overfit", "score": 10.0}]}))
    (tmp_path / "scores.json").write_text(json.dumps({
        "rounds": [
            {"round": 1, "composite": 1.0, "quality": 7.29,
             "gate_pass_rates": {"is_one_word": 1.0}, "cases": [{"case_id": "c1", "output": "Paris"}]},
            {"round": 2, "composite": 1.0, "quality": 9.0,
             "gate_pass_rates": {"is_one_word": 1.0}, "cases": [{"case_id": "c1", "output": "Paris"}]}
        ], "best_round": 2}))
    p = build_state_payload(tmp_path)
    assert p["phase"] == "done"
    assert p["met"] is True
    assert p["best"]["round"] == 2
    assert p["baseline"]["composite"] == 0.75
    assert len(p["rounds"]) == 2
    assert p["rounds"][0]["quality"] == 7.29
    assert p["rounds"][1]["quality"] == 9.0
    assert p["best_round"] == 2


def test_payload_includes_winner_diff_and_quality(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"phase": "done", "met": True}))
    (tmp_path / "winner.diff").write_text("--- baseline\n+++ round_2\n-old\n+new")
    (tmp_path / "quality.json").write_text(json.dumps(
        {"round": 2, "quality": 9.0, "quality_dims": [{"dim": "clarity", "score": 9.0}],
         "maker_feedback": "clean"}))
    p = build_state_payload(tmp_path)
    assert "winner_diff" in p
    assert "+new" in p["winner_diff"]
    assert p["latest_quality"]["quality"] == 9.0
