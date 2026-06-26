from __future__ import annotations
import yaml
from loop_iter.state import RunPaths, load_scores, load_state, write_state, _now, recompute_best

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
    not met & round >= max_rounds -> done (met=false). Refuses if phase != goalcheck.
    Quality guardrail: if baseline_quality is set and this round's quality regressed below
    baseline - tolerance, met is forced False (even if composite met). Quality never enters
    the composite; it only gates met and breaks ties in best selection.
    A round with no quality signal (None — e.g. flaky quality-judge degraded, or no quality.md)
    never triggers the guardrail: met can still pass and the round can be best (quality is treated
    as absent, not as failing). This mirrors the judge's degrade-to-None contract."""
    goal = yaml.safe_load(open(goal_path))
    st = load_state(rp)
    if st["phase"] != "goalcheck":
        raise RuntimeError(f"phase guard: goalcheck requires phase=goalcheck, got {st['phase']!r}")
    v = check_latest(rp, goal_path, best_gate_rates)
    # quality guardrail
    tol = goal.get("quality_tolerance", 0.5)
    bq = st.get("baseline_quality")
    rounds = load_scores(rp).get("rounds", [])
    latest_q = rounds[-1].get("quality") if rounds else None
    if bq is not None and latest_q is not None and latest_q < bq - tol:
        if v["met"]:
            v["met"] = False
            v["reason"] = (f"quality regression: {latest_q:.2f} < baseline {bq:.2f} "
                           f"- tol {tol}")
    # quality_target: an absolute floor on quality (opt-in). When set, met requires quality >= target.
    qt = goal.get("quality_target")
    if qt is not None and latest_q is not None and latest_q < qt:
        if v["met"]:
            v["met"] = False
            v["reason"] = (f"quality below target: {latest_q:.2f} < quality_target {qt}")
    # phase transition
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
    # best selection (only at done): quality tiebreak + exclude regressed
    if st["phase"] == "done":
        best_round = recompute_best(rp, bq, tol)
        if best_round is not None:
            data = load_scores(rp)
            br = next(r for r in data["rounds"] if r["round"] == best_round)
            st["best"] = {"round": br["round"], "composite": br["composite"], "worktree": None}
            write_state(rp, st)
    v["phase"] = st["phase"]
    return v
