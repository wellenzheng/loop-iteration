from __future__ import annotations
from loop_iter.gates import load_gates, run_gates
from loop_iter.judge import judge_case as _default_judge
from loop_iter.scoring import composite, gate_pass_rates, judge_means
from loop_iter.adapter_generic import ServiceAdapter

def run_cases(cases: list[dict], worktree: str,
              gates_path: str, rubric_md: str, weights: dict[str, float],
              run_case_fn, judge_case_fn=_default_judge, llm_call=None) -> dict:
    """Run every case through run_case_fn(case, worktree), then gates + judge -> RunScores.

    judge_case_fn defaults to loop_iter.judge.judge_case; tests inject a stub.
    A None judge result for a case => no dims for that case (gates-only contribution).
    llm_call is forwarded to judge_case_fn (real judge uses it; stubs ignore it).
    """
    gates = load_gates(gates_path)
    service = run_case_fn if isinstance(run_case_fn, ServiceAdapter) else None
    case_scores: list[dict] = []
    if service is not None:
        service.start(worktree)
    try:
        for case in cases:
            result = (service.run_case(case, worktree) if service is not None
                      else run_case_fn(case, worktree))
            gate_results = run_gates(result, case, gates)
            judged = judge_case_fn(result, case, rubric_md, llm_call)
            case_scores.append({
                "case_id": case["id"],
                "output": result.get("output", ""),
                "trace": result.get("trace") or {},
                "gates": gate_results,
                "judge": judged or [],
                "error": result.get("error"),
            })
    finally:
        if service is not None:
            service.stop()
    return {
        "cases": case_scores,
        "composite": composite(case_scores, weights),
        "gate_pass_rates": gate_pass_rates(case_scores),
        "judge_means": judge_means(case_scores),
    }
