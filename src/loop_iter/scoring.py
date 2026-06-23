from __future__ import annotations

def gate_pass_rates(case_scores: list[dict]) -> dict[str, float]:
    """Fraction of cases each gate passed (0-1)."""
    names: list[str] = []
    seen: set[str] = set()
    for c in case_scores:
        for g in c.get("gates", []):
            if g["gate"] not in seen:
                seen.add(g["gate"]); names.append(g["gate"])
    rates: dict[str, float] = {}
    for name in names:
        rows = [g for c in case_scores for g in c.get("gates", []) if g["gate"] == name]
        rates[name] = sum(1 for g in rows if g["passed"]) / len(rows) if rows else 0.0
    return rates


def judge_means(case_scores: list[dict]) -> dict[str, float]:
    """Mean score per judge dim across cases (0-10)."""
    names: list[str] = []
    seen: set[str] = set()
    for c in case_scores:
        for d in c.get("judge", []):
            if d["dim"] not in seen:
                seen.add(d["dim"]); names.append(d["dim"])
    means: dict[str, float] = {}
    for name in names:
        vals = [d["score"] for c in case_scores for d in c.get("judge", []) if d["dim"] == name]
        means[name] = sum(vals) / len(vals) if vals else 0.0
    return means


def composite(case_scores: list[dict], weights: dict[str, float]) -> float:
    """Weighted composite in 0-1. weights has key 'gates' + judge dim names."""
    gpr = gate_pass_rates(case_scores)
    jm = judge_means(case_scores)
    gates_component = sum(gpr.values()) / len(gpr) if gpr else 0.0
    acc = 0.0
    w_total = 0.0
    if "gates" in weights:
        acc += weights["gates"] * gates_component
        w_total += weights["gates"]
    for dim, score10 in jm.items():
        w = weights.get(dim, 0.0)
        acc += w * (score10 / 10.0)
        w_total += w
    return acc / w_total if w_total else 0.0


def regressed_gates(current: dict[str, float], best: dict[str, float]) -> list[str]:
    return [g for g, r in current.items() if g in best and r < best[g]]


def goal_met(round_idx: int, case_scores: list[dict], weights: dict[str, float],
             threshold: float, max_rounds: int, best_gate_rates: dict[str, float] | None,
             regression_policy: str = "block") -> dict:
    gpr = gate_pass_rates(case_scores)
    comp = composite(case_scores, weights)
    best = best_gate_rates or {}
    regressed = regressed_gates(gpr, best)
    blocked = regression_policy == "block" and bool(regressed)
    within = round_idx <= max_rounds
    met = (comp >= threshold) and (not blocked) and within
    if not within:
        reason = f"hit max_rounds ({max_rounds})"
    elif blocked:
        reason = f"gate regression: {regressed}"
    elif comp < threshold:
        reason = f"composite {comp:.3f} < threshold {threshold}"
    else:
        reason = "met"
    return {"met": met, "round": round_idx, "composite": comp,
            "gate_pass_rates": gpr, "regressed_gates": regressed, "reason": reason}
