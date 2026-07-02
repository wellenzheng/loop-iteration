from loop_iter.latency_feedback import latency_feedback


def test_feedback_with_timings_top_phases():
    round_cases = [
        {"case_id": "c1", "elapsed_ms": 1200.0, "trace": {"timings": [
            {"phase": "llm_call", "ms": 800.0, "count": 1},
            {"phase": "tool_call:kb_search", "ms": 400.0, "count": 1},
        ]}},
    ]
    baseline_cases = [
        {"case_id": "c1", "elapsed_ms": 600.0, "trace": {"timings": [
            {"phase": "llm_call", "ms": 500.0, "count": 1},
            {"phase": "tool_call:kb_search", "ms": 100.0, "count": 1},
        ]}},
    ]
    out = latency_feedback(round_cases, baseline_cases)
    assert "tool_call:kb_search" in out  # +300ms, biggest increase
    assert "llm_call" in out


def test_feedback_without_timings_falls_back_to_per_case():
    round_cases = [
        {"case_id": "c5", "elapsed_ms": 1200.0, "trace": {}},
        {"case_id": "c1", "elapsed_ms": 300.0, "trace": {}},
    ]
    baseline_cases = [
        {"case_id": "c5", "elapsed_ms": 900.0, "trace": {}},
        {"case_id": "c1", "elapsed_ms": 300.0, "trace": {}},
    ]
    out = latency_feedback(round_cases, baseline_cases)
    assert "c5" in out  # slowest delta (+300ms)
    assert "baseline" in out


def test_feedback_baseline_missing_reports_round_only():
    round_cases = [
        {"case_id": "c1", "elapsed_ms": 500.0, "trace": {"timings": [
            {"phase": "llm_call", "ms": 500.0, "count": 1},
        ]}},
    ]
    out = latency_feedback(round_cases, None)
    assert "llm_call" in out
    assert "500ms" in out


def test_feedback_empty_round_returns_empty():
    assert latency_feedback([], None) == ""


def test_feedback_skips_malformed_timing_entry():
    round_cases = [
        {"case_id": "c1", "elapsed_ms": 500.0, "trace": {"timings": [
            {"phase": "llm_call", "ms": "fast", "count": 1},     # malformed -> skipped
            {"phase": "tool_call:kb_search", "ms": 400.0, "count": 1},
        ]}},
    ]
    out = latency_feedback(round_cases, None)
    assert "tool_call:kb_search" in out   # the well-formed phase still reported
    assert "llm_call" not in out          # the malformed phase was skipped
