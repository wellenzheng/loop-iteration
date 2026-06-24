from __future__ import annotations
import yaml
from loop_iter.state import RunPaths, load_scores, load_state, write_state, _now

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


def check_and_advance(rp: RunPaths, goal_path: str, best_gate_rates: dict | None) -> dict:
    """State-machine goal-check: compute verdict, then advance phase.
    met -> done (met=true); not met & round < max_rounds -> maker + round++;
    not met & round >= max_rounds -> done (met=false). Refuses if phase != goalcheck."""
    goal = yaml.safe_load(open(goal_path))
    st = load_state(rp)
    if st["phase"] != "goalcheck":
        raise RuntimeError(f"phase guard: goalcheck requires phase=goalcheck, got {st['phase']!r}")
    v = check_latest(rp, goal_path, best_gate_rates)
    if v["met"]:
        st["met"] = True
        st["phase"] = "done"
    elif st["round"] >= goal["max_rounds"]:
        st["met"] = False
        st["phase"] = "done"
    else:
        st["met"] = False
        st["round"] = st["round"] + 1
        st["phase"] = "maker"
    st["updated_at"] = _now()
    write_state(rp, st)
    v["phase"] = st["phase"]
    return v
