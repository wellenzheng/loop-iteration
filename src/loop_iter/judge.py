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

def judge_case(result: dict, case: dict, judge_md: str, llm_call,
               model: str = "glm-4.7") -> list[dict] | None:
    """Ask the LLM to score the case per the rubric. Returns [{dim, score}] or None.

    None is the gates-only fallback signal (no hand-rolled JSON repair — strict output,
    one retry, then degrade). llm_call(prompt, model) -> str.
    """
    prompt = (
        f"{judge_md}\n\n"
        f"Return ONLY strict JSON: {{\"dims\": [{{\"dim\": <name>, \"score\": <0-10>}}]}}.\n"
        f"Case query: {case.get('query')}\n"
        f"Expected: {case.get('expected')}\n"
        f"Agent output: {result.get('output')}\n"
    )
    for _ in range(2):  # initial + one retry
        dims = _parse_dims(llm_call(prompt, model))
        if dims is not None:
            return dims
    return None
