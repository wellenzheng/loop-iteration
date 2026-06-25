from loop_iter.quality_prog import no_overfit_score

def test_no_hardcoding_scores_10():
    cases = [{"id": "c1", "query": "What is the capital of France?", "expected": "Paris"}]
    # harness has general rules, no "paris", no verbatim query
    assert no_overfit_score("Answer in one word, no punctuation.", cases) == 10.0

def test_expected_answer_in_harness_scores_low():
    cases = [{"id": "c1", "query": "capital of France?", "expected": "Paris"}]
    assert no_overfit_score("For France answer Paris.", cases) == 0.0  # "paris" present -> hardcoded

def test_query_verbatim_in_harness_detected():
    cases = [{"id": "c1", "query": "a distinctive long query here", "expected": None}]
    assert no_overfit_score("When asked: a distinctive long query here -> X", cases) == 0.0

def test_short_expected_below_threshold_not_flagged():
    # expected len < 3 is not distinctive enough to flag (avoid false positives on tiny tokens)
    cases = [{"id": "c1", "query": "hi", "expected": "hi"}]
    assert no_overfit_score("say hi", cases) == 10.0  # "hi" (len 2) below threshold

def test_partial_hardcoding_scales():
    cases = [{"id": "c1", "query": "q one here", "expected": "Paris"},
             {"id": "c2", "query": "q two here", "expected": "Tokyo"}]
    # only "paris" present (1 of 2 hardcoded) -> 10 * (1 - 1/2) = 5.0
    assert no_overfit_score("answer Paris generally", cases) == 5.0

def test_no_cases_scores_10():
    assert no_overfit_score("any harness", []) == 10.0

def test_case_insensitive():
    cases = [{"id": "c1", "query": "x", "expected": "PaRiS"}]
    assert no_overfit_score("the answer is paris", cases) == 0.0
