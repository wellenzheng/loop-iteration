from loop_iter.state import RunPaths, append_round, load_scores
from loop_iter.scoring import goal_met, composite


def test_golden_round_score_rises_until_goal_met(tmp_path):
    """Round 1 fails is_one_word (multi-word); after the maker 'sharpens' the skill,
    round 2 outputs one word -> gate passes, composite >= threshold."""
    rp = RunPaths(base=str(tmp_path), run_id="golden")
    cases = [{"id": "c1", "query": "q", "expected": None},
             {"id": "c2", "query": "q", "expected": None}]
    weights = {"gates": 2.0, "conciseness": 1.0}

    def cs(gates_passed, judge_score):
        return [{"case_id": c["id"],
                 "gates": [{"gate": "is_one_word", "passed": gates_passed}],
                 "judge": [{"dim": "conciseness", "score": judge_score}],
                 "error": None} for c in cases]

    # Round 1: gate fails, low judge
    r1 = {"round": 1, "cases": cs(gates_passed=False, judge_score=3.0),
          "gate_pass_rates": {"is_one_word": 0.0}, "judge_means": {"conciseness": 3.0}}
    r1["composite"] = composite(r1["cases"], weights)
    append_round(rp, r1)
    v1 = goal_met(1, r1["cases"], weights, threshold=0.85, max_rounds=3,
                  best_gate_rates=None, regression_policy="block")
    assert v1["met"] is False

    # Round 2: gate passes, full judge
    r2 = {"round": 2, "cases": cs(gates_passed=True, judge_score=10.0),
          "gate_pass_rates": {"is_one_word": 1.0}, "judge_means": {"conciseness": 10.0}}
    r2["composite"] = composite(r2["cases"], weights)
    append_round(rp, r2)
    v2 = goal_met(2, r2["cases"], weights, threshold=0.85, max_rounds=3,
                  best_gate_rates={"is_one_word": 1.0}, regression_policy="block")
    assert v2["met"] is True
    assert v2["composite"] >= 0.85
    assert load_scores(rp)["best_round"] == 2


def test_golden_round_regression_is_blocked(tmp_path):
    """A candidate that regresses a gate vs best-so-far is blocked even if composite rose."""
    rp = RunPaths(base=str(tmp_path), run_id="reg")
    weights = {"gates": 2.0, "conciseness": 1.0}
    best = {"is_one_word": 1.0}  # previously achieved perfect gate
    reg_cases = [{"case_id": "c1",
                  "gates": [{"gate": "is_one_word", "passed": False}],
                  "judge": [{"dim": "conciseness", "score": 10.0}], "error": None}]
    v = goal_met(2, reg_cases, weights, threshold=0.5, max_rounds=3,
                 best_gate_rates=best, regression_policy="block")
    assert v["regressed_gates"] == ["is_one_word"]
    assert v["met"] is False
