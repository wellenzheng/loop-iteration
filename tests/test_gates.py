from loop_iter.gates import load_gates, run_gates


def test_load_gates_imports_GATES_dict(tmp_path):
    mod = tmp_path / "gates.py"
    mod.write_text(
        "def _exact(result, case):\n"
        "    return {'passed': result['output'].strip() == case['expected'].strip()}\n"
        "GATES = {'exact': _exact}\n"
    )
    gates = load_gates(str(mod))
    assert "exact" in gates


def test_run_gates_collects_pass_fail(tmp_path):
    mod = tmp_path / "gates.py"
    mod.write_text(
        "def _exact(result, case):\n"
        "    return {'passed': result['output'].strip() == case['expected'].strip()}\n"
        "GATES = {'exact': _exact}\n"
    )
    gates = load_gates(str(mod))
    result = {"output": "Paris", "trace": {}, "error": None}
    case = {"id": "c1", "query": "capital of France?", "expected": "Paris"}
    out = run_gates(result, case, gates)
    assert out == [{"gate": "exact", "passed": True}]


def test_run_gates_swallows_gate_exception_as_fail(tmp_path):
    mod = tmp_path / "gates.py"
    mod.write_text(
        "def _boom(result, case):\n"
        "    raise RuntimeError('x')\n"
        "GATES = {'boom': _boom}\n"
    )
    gates = load_gates(str(mod))
    out = run_gates({"output": "", "trace": {}, "error": None},
                    {"id": "c1", "query": "q", "expected": "a"}, gates)
    assert out == [{"gate": "boom", "passed": False}]
