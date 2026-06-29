from loop_iter.case_runner import run_cases

def _stub_run_case(output_map):
    def rc(case, worktree):
        return {"case_id": case["id"], "output": output_map[case["id"]],
                "trace": {}, "error": None}
    return rc

def _gate_mod(tmp_path):
    p = tmp_path / "gates.py"
    p.write_text(
        "def _ok(result, case):\n"
        "    return {'passed': 'OK' in result['output']}\n"
        "GATES = {'has_ok': _ok}\n"
    )
    return str(p)

def test_run_cases_computes_composite(tmp_path):
    cases = [{"id": "c1", "query": "q", "expected": None},
             {"id": "c2", "query": "q", "expected": None}]
    rc = _stub_run_case({"c1": "OK", "c2": "nope"})
    judge = lambda result, case, rubric_md, llm_call: [{"dim": "tone", "score": 10.0}]
    out = run_cases(
        cases=cases, worktree="/tmp/ignored",
        gates_path=_gate_mod(tmp_path), rubric_md="x",
        weights={"gates": 1.0, "tone": 1.0},
        run_case_fn=rc, judge_case_fn=judge, llm_call=None,
    )
    assert out["composite"] == 0.75
    assert out["gate_pass_rates"] == {"has_ok": 0.5}
    assert len(out["cases"]) == 2

def test_run_cases_falls_back_to_gates_only_when_judge_none(tmp_path):
    cases = [{"id": "c1", "query": "q", "expected": None}]
    rc = _stub_run_case({"c1": "OK"})
    judge = lambda *a, **k: None
    out = run_cases(
        cases=cases, worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), rubric_md="x",
        weights={"gates": 1.0, "tone": 1.0},
        run_case_fn=rc, judge_case_fn=judge, llm_call=None,
    )
    assert out["composite"] == 1.0
    assert out["judge_means"] == {}


def test_run_cases_wraps_service_adapter_start_once_stop_in_finally():
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import ServiceAdapter

    class FakeService(ServiceAdapter):
        def __init__(self):
            super().__init__({}); self.started = 0; self.stopped = 0; self.calls = []
        def start(self, worktree): self.started += 1
        def run_case(self, case, worktree):
            self.calls.append(case["id"])
            return {"case_id": case["id"], "output": "one", "trace": {}, "error": None}
        def stop(self): self.stopped += 1

    cases = [{"id": "c1", "query": "q1"}, {"id": "c2", "query": "q2"}, {"id": "c3", "query": "q3"}]
    import tempfile, os
    gates_py = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False); gates_py.write("GATES = {}\n"); gates_py.close()
    try:
        svc = FakeService()
        out = run_cases(cases, "/tmp/wt", gates_py.name, "judge", {"gates": 1.0},
                        run_case_fn=svc, judge_case_fn=lambda *a, **k: [])
        assert svc.started == 1
        assert svc.stopped == 1
        assert svc.calls == ["c1", "c2", "c3"]
        assert out["composite"] is not None
    finally:
        os.unlink(gates_py.name)


def test_run_cases_stops_service_even_on_exception():
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import ServiceAdapter

    class BoomService(ServiceAdapter):
        def __init__(self): super().__init__({}); self.stopped = 0
        def start(self, worktree): pass
        def run_case(self, case, worktree): raise RuntimeError("boom")
        def stop(self): self.stopped += 1

    import tempfile, os
    gates_py = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False); gates_py.write("GATES = {}\n"); gates_py.close()
    try:
        svc = BoomService()
        import pytest
        with pytest.raises(RuntimeError):
            run_cases([{"id": "c1", "query": "q"}], "/tmp/wt", gates_py.name, "j", {"gates": 1.0},
                      run_case_fn=svc, judge_case_fn=lambda *a, **k: [])
        assert svc.stopped == 1
    finally:
        os.unlink(gates_py.name)


def test_run_cases_parallel_preserves_order_and_runs_concurrently(tmp_path):
    import threading, time
    state = {"inflight": 0, "maxinflight": 0}
    lock = threading.Lock()

    def rc(case, worktree):
        with lock:
            state["inflight"] += 1
            state["maxinflight"] = max(state["maxinflight"], state["inflight"])
        time.sleep(0.05)  # releases the GIL -> real overlap is possible
        with lock:
            state["inflight"] -= 1
        return {"case_id": case["id"], "output": "OK", "trace": {}, "error": None}

    cases = [{"id": f"c{i}", "query": "q", "expected": None} for i in range(6)]
    out = run_cases(
        cases=cases, worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), rubric_md="x",
        weights={"gates": 1.0},
        run_case_fn=rc, judge_case_fn=lambda *a, **k: [],
        llm_call=None, parallelism=4,
    )
    # results come back in original case order
    assert [c["case_id"] for c in out["cases"]] == [c["id"] for c in cases]
    # cases actually overlapped (not a serialized pool)
    assert state["maxinflight"] > 1
    assert out["composite"] == 1.0


def test_run_cases_serial_by_default_never_overlaps(tmp_path):
    import threading, time
    state = {"inflight": 0, "maxinflight": 0}
    lock = threading.Lock()

    def rc(case, worktree):
        with lock:
            state["inflight"] += 1
            state["maxinflight"] = max(state["maxinflight"], state["inflight"])
        time.sleep(0.02)
        with lock:
            state["inflight"] -= 1
        return {"case_id": case["id"], "output": "OK", "trace": {}, "error": None}

    cases = [{"id": f"c{i}", "query": "q", "expected": None} for i in range(4)]
    out = run_cases(
        cases=cases, worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), rubric_md="x",
        weights={"gates": 1.0},
        run_case_fn=rc, judge_case_fn=lambda *a, **k: [],
        llm_call=None,  # parallelism omitted -> serial, on the calling thread
    )
    assert state["maxinflight"] == 1
    assert [c["case_id"] for c in out["cases"]] == [c["id"] for c in cases]
