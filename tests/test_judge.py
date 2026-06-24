import json
from loop_iter.judge import judge_case


def _llm_returning(payload):
    return lambda prompt, model: json.dumps(payload)


def test_judge_case_parses_strict_json():
    llm = _llm_returning({"dims": [{"dim": "tone", "score": 8.0}]})
    out = judge_case(
        result={"output": "hi", "trace": {}, "error": None},
        case={"id": "c1", "query": "q", "expected": None},
        judge_md="Score tone 0-10.",
        llm_call=llm,
    )
    assert out == [{"dim": "tone", "score": 8.0}]


def test_judge_case_retries_then_falls_back_to_none():
    calls = {"n": 0}
    def llm(prompt, model):
        calls["n"] += 1
        return "not json at all {{{"   # unparseable every time
    out = judge_case(
        result={"output": "hi", "trace": {}, "error": None},
        case={"id": "c1", "query": "q", "expected": None},
        judge_md="x",
        llm_call=llm,
    )
    assert out is None          # gates-only fallback signal
    assert calls["n"] == 2      # one retry


def test_judge_case_succeeds_on_retry():
    seq = iter(["garbage", json.dumps({"dims": [{"dim": "tone", "score": 7.0}]})])
    out = judge_case(
        result={"output": "hi", "trace": {}, "error": None},
        case={"id": "c1", "query": "q", "expected": None},
        judge_md="x",
        llm_call=lambda p, m: next(seq),
    )
    assert out == [{"dim": "tone", "score": 7.0}]


def test_judge_case_falls_back_when_llm_call_raises():
    calls = {"n": 0}
    def llm(prompt, model):
        calls["n"] += 1
        raise RuntimeError("network timeout")  # transport/timeout-style error
    out = judge_case(
        result={"output": "hi", "trace": {}, "error": None},
        case={"id": "c1", "query": "q", "expected": None},
        judge_md="x",
        llm_call=llm,
    )
    assert out is None          # gates-only fallback, never crashed the round
    assert calls["n"] == 2      # still retried once before giving up


from loop_iter.judge import judge_quality, quality_mean

def test_quality_mean_of_dims():
    assert quality_mean([{"dim": "clarity", "score": 8.0}, {"dim": "no_overfit", "score": 6.0}]) == 7.0

def test_quality_mean_none_and_empty():
    assert quality_mean(None) is None
    assert quality_mean([]) is None

def test_judge_quality_parses_dims():
    calls = []
    def fake_llm(prompt, model):
        calls.append(prompt)
        return '{"dims": [{"dim": "clarity", "score": 9.0}, {"dim": "maintainability", "score": 7.0}]}'
    dims = judge_quality("HARNESS TEXT", "rubric: be clear", fake_llm)
    assert dims == [{"dim": "clarity", "score": 9.0}, {"dim": "maintainability", "score": 7.0}]
    assert "HARNESS TEXT" in calls[0] and "rubric: be clear" in calls[0]

def test_judge_quality_degrades_to_none_on_bad_json():
    def fake_llm(prompt, model):
        return "not json"
    assert judge_quality("h", "r", fake_llm) is None

def test_judge_quality_degrades_to_none_on_exception():
    def fake_llm(prompt, model):
        raise RuntimeError("network")
    assert judge_quality("h", "r", fake_llm) is None

def test_judge_quality_noop_without_rubric():
    def fake_llm(prompt, model):
        raise AssertionError("must not call llm when no rubric")
    assert judge_quality("h", "", fake_llm) is None
