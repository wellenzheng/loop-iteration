"""Programmatic (non-LLM) harness-quality checks. Reliable where the LLM quality-judge degrades."""
from __future__ import annotations


def no_overfit_score(harness_text: str, cases: list[dict]) -> float:
    """Detect whether the harness hardcodes eval-specific content. Returns 0-10 (10 = none detected).

    A case counts as hardcoded if its `expected` answer (len >= 3) OR a distinctive substring of its
    `query` (len >= 8) appears verbatim (case-insensitive) in the harness. The expected-answer case is
    the classic overfit (the maker wrote the answer into the instructions); a verbatim query means the
    maker tailored the harness to that exact eval case. Short tokens (< 3 / < 8 chars) are skipped to
    avoid false positives. Score = 10 * (1 - hardcoded / len(cases)); 10.0 when no cases."""
    text = (harness_text or "").lower()
    if not cases:
        return 10.0
    hardcoded = 0
    for c in cases:
        hit = False
        exp = c.get("expected")
        if isinstance(exp, str) and len(exp) >= 3 and exp.lower() in text:
            hit = True
        q = c.get("query")
        if isinstance(q, str) and len(q) >= 8 and q.lower() in text:
            hit = True
        if hit:
            hardcoded += 1
    return 10.0 * (1 - hardcoded / len(cases))
