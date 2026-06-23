from loop_iter.scoring import gate_pass_rates, judge_means, composite, regressed_gates, goal_met


def _cs(gates, judge):
    return {"case_id": "x", "gates": gates, "judge": judge, "error": None}


def test_gate_pass_rates_all_pass():
    cases = [_cs([{"gate": "exact", "passed": True}], [])] * 3
    assert gate_pass_rates(cases) == {"exact": 1.0}


def test_gate_pass_rates_partial():
    cases = [
        _cs([{"gate": "exact", "passed": True}], []),
        _cs([{"gate": "exact", "passed": False}], []),
    ]
    assert gate_pass_rates(cases) == {"exact": 0.5}


def test_judge_means():
    cases = [
        _cs([], [{"dim": "tone", "score": 8.0}]),
        _cs([], [{"dim": "tone", "score": 6.0}]),
    ]
    assert judge_means(cases) == {"tone": 7.0}


def test_composite_weights_gates_and_judge():
    cases = [_cs([{"gate": "exact", "passed": True}], [{"dim": "tone", "score": 10.0}])]
    assert composite(cases, {"gates": 1.0, "tone": 1.0}) == 1.0


def test_composite_mixed():
    cases = [_cs([{"gate": "exact", "passed": False}], [{"dim": "tone", "score": 5.0}])]
    assert composite(cases, {"gates": 1.0, "tone": 1.0}) == 0.25


def test_regressed_gates_detects_drop():
    assert regressed_gates({"a": 0.5, "b": 1.0}, {"a": 1.0, "b": 0.5}) == ["a"]


def test_goal_met_when_above_threshold_no_regression():
    cases = [_cs([{"gate": "exact", "passed": True}], [{"dim": "tone", "score": 10.0}])]
    v = goal_met(round_idx=1, case_scores=cases, weights={"gates": 1.0, "tone": 1.0},
                 threshold=0.8, max_rounds=3, best_gate_rates={"exact": 1.0})
    assert v["met"] is True
    assert v["composite"] == 1.0
    assert v["regressed_gates"] == []


def test_goal_not_met_when_gate_regressed_and_policy_block():
    cases = [_cs([{"gate": "exact", "passed": False}], [{"dim": "tone", "score": 10.0}])]
    v = goal_met(round_idx=1, case_scores=cases, weights={"gates": 1.0, "tone": 1.0},
                 threshold=0.5, max_rounds=3, best_gate_rates={"exact": 1.0},
                 regression_policy="block")
    assert v["met"] is False
    assert v["regressed_gates"] == ["exact"]


def test_goal_not_met_when_over_max_rounds():
    cases = [_cs([{"gate": "exact", "passed": True}], [{"dim": "tone", "score": 10.0}])]
    v = goal_met(round_idx=4, case_scores=cases, weights={"gates": 1.0, "tone": 1.0},
                 threshold=0.8, max_rounds=3, best_gate_rates={"exact": 1.0})
    assert v["met"] is False
