import yaml
from loop_iter.state import RunPaths, append_round
from loop_iter.goal_check import check_latest

def _goal(tmp_path, threshold=0.8, max_rounds=3, regression="block"):
    g = {"threshold": threshold, "max_rounds": max_rounds,
         "weights": {"gates": 1.0, "tone": 1.0}, "regression": regression}
    (tmp_path / "goal.yaml").write_text(yaml.safe_dump(g))
    return str(tmp_path / "goal.yaml")

def test_check_latest_met(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    append_round(rp, {"round": 1, "composite": 0.9,
                      "gate_pass_rates": {"exact": 1.0}, "judge_means": {}, "cases": []})
    v = check_latest(rp, _goal(tmp_path), best_gate_rates={"exact": 1.0})
    assert v["met"] is True

def test_check_latest_not_met_below_threshold(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    append_round(rp, {"round": 1, "composite": 0.5,
                      "gate_pass_rates": {"exact": 1.0}, "judge_means": {}, "cases": []})
    v = check_latest(rp, _goal(tmp_path), best_gate_rates={"exact": 1.0})
    assert v["met"] is False
