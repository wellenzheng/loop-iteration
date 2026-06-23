from __future__ import annotations
from loop_iter.gates import load_gates, run_gates
from loop_iter.judge import judge_case as _default_judge
from loop_iter.scoring import composite, gate_pass_rates, judge_means

def run_cases(cases: list[dict], worktree: str, agent_subdir: str,
              gates_path: str, judge_md: str, weights: dict[str, float],
              run_case_fn, judge_case_fn=_default_judge, llm_call=None) -> dict:
    """Run every case through run_case_fn, then gates + judge -> RunScores.

    judge_case_fn defaults to loop_iter.judge.judge_case; tests inject a stub.
    A None judge result for a case => no dims for that case (gates-only contribution).
    llm_call is forwarded to judge_case_fn (the real judge uses it; stubs ignore it).
    """
    gates = load_gates(gates_path)
    case_scores: list[dict] = []
    for case in cases:
        result = run_case_fn(case, worktree, agent_subdir)
        gate_results = run_gates(result, case, gates)
        judged = judge_case_fn(result, case, judge_md, llm_call)
        case_scores.append({
            "case_id": case["id"],
            "gates": gate_results,
            "judge": judged or [],
            "error": result.get("error"),
        })
    return {
        "cases": case_scores,
        "composite": composite(case_scores, weights),
        "gate_pass_rates": gate_pass_rates(case_scores),
        "judge_means": judge_means(case_scores),
    }


def _cli():
    import argparse, json, yaml, importlib.util
    from loop_iter.state import RunPaths, append_round
    ap = argparse.ArgumentParser(prog="python -m loop_iter.case_runner")
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--agent-subdir", required=True)
    ap.add_argument("--eval", required=True, help="path to eval dir (goal.yaml etc.)")
    ap.add_argument("--adapter", required=True, help="path to adapter run_case.py")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--base", default=".")
    ap.add_argument("--round", type=int, required=True)
    a = ap.parse_args()

    ev = a.eval
    goal = yaml.safe_load(open(f"{ev}/goal.yaml"))
    cases = json.load(open(f"{ev}/cases.json"))
    spec = importlib.util.spec_from_file_location("adapter_run_case", a.adapter)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

    from loop_iter.llm_client import chat as llm_call
    out = run_cases(cases, a.worktree, a.agent_subdir, f"{ev}/gates.py",
                    open(f"{ev}/judge.md").read(), goal["weights"],
                    run_case_fn=mod.run_case, llm_call=llm_call)
    out["round"] = a.round
    rp = RunPaths(base=a.base, run_id=a.run_id)
    append_round(rp, out)
    print(json.dumps({"round": a.round, "composite": out["composite"],
                      "gate_pass_rates": out["gate_pass_rates"]}, indent=2))

if __name__ == "__main__":
    _cli()
