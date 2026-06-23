def is_one_word(result, case):
    """Output must be a single word, no punctuation."""
    out = result["output"].strip().rstrip(".!?")
    return {"passed": len(out.split()) == 1}

def matches_expected(result, case):
    """Case-insensitive match against expected (if provided)."""
    if not case.get("expected"):
        return {"passed": True}
    return {"passed": result["output"].strip().rstrip(".!?").lower() == case["expected"].lower()}

GATES = {"is_one_word": is_one_word, "matches_expected": matches_expected}
