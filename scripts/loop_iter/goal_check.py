from __future__ import annotations
import json
import yaml
from loop_iter.state import RunPaths, load_scores

def check_latest(rp: RunPaths, goal_path: str, best_gate_rates: dict | None) -> dict:
    """Read the latest round's stored composite + gate_pass_rates + goal -> GoalVerdict."""
    goal = yaml.safe_load(open(goal_path))
    data = load_scores(rp)
    if not data.get("rounds"):
        return {"met": False, "round": 0, "composite": 0.0,
                "gate_pass_rates": {}, "regressed_gates": [], "reason": "no rounds yet"}
    latest = data["rounds"][-1]
    gpr = latest.get("gate_pass_rates", {})
    comp = latest.get("composite", 0.0)
    best = best_gate_rates or {}
    regressed = [g for g, r in gpr.items() if g in best and r < best[g]]
    blocked = goal.get("regression", "block") == "block" and bool(regressed)
    within = latest["round"] <= goal["max_rounds"]
    met = (comp >= goal["threshold"]) and (not blocked) and within
    if not within:
        reason = f"hit max_rounds ({goal['max_rounds']})"
    elif blocked:
        reason = f"gate regression: {regressed}"
    elif comp < goal["threshold"]:
        reason = f"composite {comp:.3f} < threshold {goal['threshold']}"
    else:
        reason = "met"
    return {"met": met, "round": latest["round"], "composite": comp,
            "gate_pass_rates": gpr, "regressed_gates": regressed, "reason": reason}

def _cli():
    import argparse
    ap = argparse.ArgumentParser(prog="python -m loop_iter.goal_check")
    ap.add_argument("--eval", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--base", default=".")
    ap.add_argument("--best-gate-rates", default=None,
                    help="JSON of best-so-far gate pass rates; omit on round 1")
    a = ap.parse_args()
    rp = RunPaths(base=a.base, run_id=a.run_id)
    best = json.loads(a.best_gate_rates) if a.best_gate_rates else None
    v = check_latest(rp, f"{a.eval}/goal.yaml", best)
    print(json.dumps(v, indent=2))
    raise SystemExit(0 if v["met"] else 1)

if __name__ == "__main__":
    _cli()
