from __future__ import annotations
import concurrent.futures
from loop_iter.gates import load_gates, run_gates
from loop_iter.judge import judge_case as _default_judge
from loop_iter.scoring import composite, gate_pass_rates, judge_means
from loop_iter.adapter_generic import ServiceAdapter

def run_cases(cases: list[dict], worktree: str,
              gates_path: str, rubric_md: str, weights: dict[str, float],
              run_case_fn, judge_case_fn=_default_judge, llm_call=None,
              parallelism: int = 1) -> dict:
    """Run every case through run_case_fn(case, worktree), then gates + judge -> RunScores.

    judge_case_fn defaults to loop_iter.judge.judge_case; tests inject a stub.
    A None judge result for a case => no dims for that case (gates-only contribution).
    llm_call is forwarded to judge_case_fn (real judge uses it; stubs ignore it).

    parallelism: max concurrent cases (default 1 = serial ON THE CALLING THREAD).
    >1 runs the per-case pipeline (run_case -> gates -> judge) on a ThreadPoolExecutor.
    Safe when the per-case run_case call holds no shared mutable state across calls:
    claude-p/command (subprocess per call), local-service (transient httpx), and
    llm_client.chat + run_gates are all thread-safe. python-import is safe when the shim
    builds fresh per-call state (the maas shim's asyncio.run per call is thread-local);
    custom adapter.py is safe when start()'s module globals are only read by run_case and
    run_case itself is thread-safe. validate_spec warns for python-import>1; smoke-test it.
    Results are returned in original case order (executor.map preserves submission order).
    """
    gates = load_gates(gates_path)
    service = run_case_fn if isinstance(run_case_fn, ServiceAdapter) else None

    def _run_one(case):
        result = (service.run_case(case, worktree) if service is not None
                  else run_case_fn(case, worktree))
        gate_results = run_gates(result, case, gates)
        judged = judge_case_fn(result, case, rubric_md, llm_call)
        return {
            "case_id": case["id"],
            "output": result.get("output", ""),
            "trace": result.get("trace") or {},
            "gates": gate_results,
            "judge": judged or [],
            "error": result.get("error"),
        }

    case_scores: list[dict] = []
    if service is not None:
        service.start(worktree)
    try:
        if parallelism and parallelism > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as ex:
                case_scores = list(ex.map(_run_one, cases))
        else:
            case_scores = [_run_one(c) for c in cases]
    finally:
        if service is not None:
            service.stop()
    return {
        "cases": case_scores,
        "composite": composite(case_scores, weights),
        "gate_pass_rates": gate_pass_rates(case_scores),
        "judge_means": judge_means(case_scores),
    }
