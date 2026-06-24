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


import json
from loop_iter.state import RunPaths, init_state, write_state, load_state, append_round
from loop_iter.goal_check import check_and_advance

def _goal_yaml(tmp_path, threshold=0.8, max_rounds=3):
    p = tmp_path / "goal.yaml"
    p.write_text(f"threshold: {threshold}\nmax_rounds: {max_rounds}\nweights: {{gates: 1.0}}\nregression: block\n")
    return str(p)

def test_check_and_advance_met_goes_done(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1})
    append_round(rp, {"round": 1, "composite": 0.9, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path), None)
    assert v["met"] is True
    assert load_state(rp)["phase"] == "done"
    assert load_state(rp)["met"] is True

def test_check_and_advance_not_met_under_cap_loops_to_maker(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1})
    append_round(rp, {"round": 1, "composite": 0.5, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path), None)
    assert v["met"] is False
    st = load_state(rp)
    assert st["phase"] == "maker"
    assert st["round"] == 2          # incremented for the next round

def test_check_and_advance_not_met_at_cap_goes_done(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 3})   # at cap
    append_round(rp, {"round": 3, "composite": 0.5, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path), None)
    assert v["met"] is False
    st = load_state(rp)
    assert st["phase"] == "done"     # capped, not met -> done
    assert st["round"] == 3          # NOT incremented past cap

def test_check_and_advance_refuses_wrong_phase(tmp_path):
    import pytest
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    # phase is still baseline
    with pytest.raises(RuntimeError, match="phase guard"):
        check_and_advance(rp, _goal_yaml(tmp_path), None)

def test_check_and_advance_populates_best_at_done(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 2})
    append_round(rp, {"round": 1, "composite": 0.5, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    append_round(rp, {"round": 2, "composite": 0.9, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path, threshold=0.95, max_rounds=2), None)  # not met, at cap -> done
    assert v["met"] is False
    st = load_state(rp)
    assert st["best"]["round"] == 2
    assert st["best"]["composite"] == 0.9
