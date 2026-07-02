from __future__ import annotations

def _aggregate_phases(cases: list[dict]) -> dict[str, dict]:
    """Sum ms and count per phase across cases. Returns {phase: {"ms": float, "count": int}}.
    Malformed timing entries (non-numeric ms/count, missing phase) are skipped — never raise."""
    agg: dict[str, dict] = {}
    for c in cases:
        for t in (c.get("trace") or {}).get("timings", []) or []:
            p = t.get("phase")
            if not p:
                continue
            try:
                ms = float(t.get("ms", 0.0))
                count = int(t.get("count", 0))
            except (TypeError, ValueError):
                continue
            d = agg.setdefault(p, {"ms": 0.0, "count": 0})
            d["ms"] += ms
            d["count"] += count
    return agg


def latency_feedback(round_cases: list[dict], baseline_cases: list[dict] | None = None) -> str:
    """Best-effort latency attribution for the maker. Pure function.
    - If trace.timings present: top-3 phases by ms increase vs baseline (with count delta).
    - Else: top-3 cases by elapsed_ms delta vs baseline.
    - baseline absent/missing timings: report round's own top only, no crash.
    Returns "" for empty round_cases."""
    if not round_cases:
        return ""
    round_agg = _aggregate_phases(round_cases)
    if round_agg:
        base_agg = _aggregate_phases(baseline_cases) if baseline_cases else {}
        rows = []
        for p, rd in round_agg.items():
            bd = base_agg.get(p, {"ms": 0.0, "count": 0})
            rows.append((p, rd, bd, rd["ms"] - bd["ms"]))
        rows.sort(key=lambda x: x[3], reverse=True)
        lines = ["Latency by phase (round vs baseline):"]
        for p, rd, bd, d_ms in rows[:3]:
            sign = "+" if d_ms >= 0 else ""
            lines.append(f"  {p}: {bd['count']}->{rd['count']} calls, "
                         f"{bd['ms']:.0f}->{rd['ms']:.0f}ms ({sign}{d_ms:.0f}ms)")
        return "\n".join(lines)
    # no timings -> per-case elapsed delta
    base_elapsed = {c["case_id"]: float(c.get("elapsed_ms", 0.0))
                    for c in (baseline_cases or []) if "case_id" in c}
    rows = []
    for c in round_cases:
        cid = c.get("case_id")
        r_ms = float(c.get("elapsed_ms", 0.0))
        b_ms = base_elapsed.get(cid)
        rows.append((cid, r_ms, b_ms, (r_ms - b_ms) if b_ms is not None else None))
    rows.sort(key=lambda x: (x[3] if x[3] is not None else float("-inf")), reverse=True)
    lines = ["Latency by case (round vs baseline):"]
    for cid, r_ms, b_ms, d in rows[:3]:
        if d is not None:
            sign = "+" if d >= 0 else ""
            lines.append(f"  {cid}: {r_ms:.0f}ms vs baseline {b_ms:.0f}ms ({sign}{d:.0f}ms)")
        else:
            lines.append(f"  {cid}: {r_ms:.0f}ms (no baseline)")
    return "\n".join(lines)
