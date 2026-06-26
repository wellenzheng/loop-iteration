from __future__ import annotations
import json

def _parse_dims(text: str) -> list[dict] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    dims = data.get("dims") if isinstance(data, dict) else None
    if not isinstance(dims, list):
        return None
    clean = []
    for d in dims:
        if isinstance(d, dict) and "dim" in d and "score" in d:
            try:
                clean.append({"dim": str(d["dim"]), "score": float(d["score"])})
            except (TypeError, ValueError):
                return None
    return clean or None

def judge_case(result: dict, case: dict, rubric_md: str, llm_call,
               model: str = "glm-4.7") -> list[dict] | None:
    """Ask the LLM to score the case per the rubric. Returns [{dim, score}] or None.

    None is the gates-only fallback signal — returned on unparseable output (no hand-rolled
    JSON repair: strict output, one retry, then degrade) AND on any llm_call exception
    (network/timeout/transport). A flaky judge must never crash the round; it degrades to
    gates-only for that case. llm_call(prompt, model) -> str.
    """
    prompt = (
        f"{rubric_md}\n\n"
        f"Return ONLY strict JSON: {{\"dims\": [{{\"dim\": <name>, \"score\": <0-10>}}]}}.\n"
        f"Case query: {case.get('query')}\n"
        f"Expected: {case.get('expected')}\n"
        f"Agent output: {result.get('output')}\n"
    )
    for _ in range(2):  # initial + one retry
        try:
            dims = _parse_dims(llm_call(prompt, model))
        except Exception:  # network/timeout/transport -> gates-only, never crash the round
            dims = None
        if dims is not None:
            return dims
    return None


def quality_mean(dims: list[dict] | None) -> float | None:
    """Mean dim score (0-10), or None if no dims (gates-only / degraded signal)."""
    if not dims:
        return None
    return sum(d["score"] for d in dims) / len(dims)


def judge_quality(harness_text: str, quality_md: str, llm_call,
                  model: str = "glm-4.7") -> list[dict] | None:
    """Ask the LLM to score the harness FILES per the quality rubric. Returns [{dim, score}] or None.

    Same degrade-to-None contract as judge_case: unparseable output (strict JSON, one retry, then
    degrade) AND any llm_call exception -> None. A flaky quality-judge never crashes the round; the
    guardrail simply goes inactive (treated as no quality signal) for that round. No rubric -> None
    without calling the LLM. llm_call(prompt, model) -> str."""
    if not quality_md:
        return None
    prompt = (
        f"{quality_md}\n\n"
        f"Return ONLY strict JSON: {{\"dims\": [{{\"dim\": <name>, \"score\": <0-10>}}]}}.\n"
        f"Harness files (concatenated):\n{harness_text}\n"
    )
    for _ in range(2):  # initial + one retry
        try:
            dims = _parse_dims(llm_call(prompt, model))
        except Exception:  # network/timeout/transport -> degrade, never crash
            dims = None
        if dims is not None:
            return dims
    return None
