from loop_iter.case_runner import run_cases

def _stub_run_case(output_map):
    def rc(case, worktree):
        return {"case_id": case["id"], "output": output_map[case["id"]],
                "trace": {}, "error": None}
    return rc

def _gate_mod(tmp_path):
    p = tmp_path / "gates.py"
    p.write_text(
        "def _ok(result, case):\n"
        "    return {'passed': 'OK' in result['output']}\n"
        "GATES = {'has_ok': _ok}\n"
    )
    return str(p)

def test_run_cases_computes_composite(tmp_path):
    cases = [{"id": "c1", "query": "q", "expected": None},
             {"id": "c2", "query": "q", "expected": None}]
    rc = _stub_run_case({"c1": "OK", "c2": "nope"})
    judge = lambda result, case, judge_md, llm_call: [{"dim": "tone", "score": 10.0}]
    out = run_cases(
        cases=cases, worktree="/tmp/ignored",
        gates_path=_gate_mod(tmp_path), judge_md="x",
        weights={"gates": 1.0, "tone": 1.0},
        run_case_fn=rc, judge_case_fn=judge, llm_call=None,
    )
    assert out["composite"] == 0.75
    assert out["gate_pass_rates"] == {"has_ok": 0.5}
    assert len(out["cases"]) == 2

def test_run_cases_falls_back_to_gates_only_when_judge_none(tmp_path):
    cases = [{"id": "c1", "query": "q", "expected": None}]
    rc = _stub_run_case({"c1": "OK"})
    judge = lambda *a, **k: None
    out = run_cases(
        cases=cases, worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), judge_md="x",
        weights={"gates": 1.0, "tone": 1.0},
        run_case_fn=rc, judge_case_fn=judge, llm_call=None,
    )
    assert out["composite"] == 1.0
    assert out["judge_means"] == {}
