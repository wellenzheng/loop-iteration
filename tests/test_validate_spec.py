import json
from pathlib import Path
from loop_iter.validate_spec import validate_spec


def _write_valid_spec(d: Path):
    (d / "goal.yaml").write_text(
        "threshold: 0.85\nmax_rounds: 3\nweights: {gates: 2.0, conciseness: 1.0}\nregression: block\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (d / "gates.py").write_text(
        "def g(result, case):\n    return {'passed': True}\nGATES = {'g': g}\n")
    (d / "judge.md").write_text("score conciseness 0-10")
    (d / "quality.md").write_text("clarity / no_overfit / maintainability")


def test_valid_spec(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    v = validate_spec(str(d))
    assert v["valid"] is True
    assert v["problems"] == []


def test_missing_goal_yaml(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "cases.json").write_text("[]")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("goal.yaml" in p for p in v["problems"])


def test_goal_yaml_bad_types(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: high\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text("[]")
    (d / "gates.py").write_text("GATES = {}")
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("threshold" in p for p in v["problems"])


def test_max_rounds_must_be_positive_int(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 0\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text("[]")
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("max_rounds" in p for p in v["problems"])


def test_cases_must_be_nonempty_list_with_id_query(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1"}]')  # missing query
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("query" in p for p in v["problems"])


def test_gates_py_must_define_GATES_dict_of_callables(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("GATES = {'g': 'not callable'}")  # value not callable
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("GATES" in p or "callable" in p for p in v["problems"])


def test_gates_py_syntax_error_is_problem(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("def broken(:\n")  # syntax error
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("gates.py" in p for p in v["problems"])


def test_quality_md_optional_warning(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    # no quality.md
    v = validate_spec(str(d))
    assert v["valid"] is True
    assert any("quality.md" in w for w in v["warnings"])


def test_unknown_agent_type_warns(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    goal = (d / "goal.yaml").read_text() + "agent:\n  type: bogus\n"
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("type" in p for p in v["problems"])


def test_non_dict_goal_yaml_is_problem_not_crash(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("just a string\n")  # scalar, not a mapping
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))   # must NOT raise
    assert v["valid"] is False
    assert any("mapping" in p for p in v["problems"])


def test_missing_GATES_is_problem(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("x = 1\n")  # no GATES
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("GATES" in p for p in v["problems"])


def test_bool_threshold_rejected(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: true\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("threshold" in p for p in v["problems"])


def test_local_service_requires_start_endpoint_request(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    goal = (d / "goal.yaml").read_text() + "agent:\n  type: local-service\n"
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is False
    problems = " ".join(v["problems"])
    assert "start" in problems and "endpoint" in problems and "request" in problems


def test_local_service_valid_with_full_config(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    goal = (d / "goal.yaml").read_text() + (
        "agent:\n  type: local-service\n"
        "  start: ['bash','-c','echo x']\n"
        "  endpoint: 'http://localhost:{port}/v1/chat'\n"
        "  request: '{\"query\":\"{query}\"}'\n"
        "  response_path: 'data.answer'\n")
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is True
    assert any("ready" in w for w in v["warnings"])


def test_local_service_with_ready_no_warning(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    goal = (d / "goal.yaml").read_text() + (
        "agent:\n  type: local-service\n"
        "  start: ['bash','-c','echo x']\n"
        "  ready: 'http://localhost:{port}/health'\n"
        "  endpoint: 'http://localhost:{port}/v1/chat'\n"
        "  request: '{\"query\":\"{query}\"}'\n"
        "  response_path: 'data.answer'\n")
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is True
    assert not any("ready" in w for w in v["warnings"])


def test_missing_pyyaml_reports_clear_problem(tmp_path, monkeypatch):
    import builtins
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "yaml":
            raise ImportError("no pyyaml")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("pyyaml" in p for p in v["problems"])
    assert not any("unparseable" in p for p in v["problems"])


def test_adapter_py_optional_no_warning(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    v = validate_spec(str(d))
    assert v["valid"] is True
    assert not any("adapter.py" in w for w in v["warnings"])


def test_adapter_py_present_no_problem(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    (d / "adapter.py").write_text(
        "def start(w): pass\n"
        "def run_case(c, w): return {}\n"
        "def stop(): pass\n")
    v = validate_spec(str(d))
    assert v["valid"] is True


def test_adapter_py_info_warning_when_present(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    (d / "adapter.py").write_text(
        "def start(w): pass\n"
        "def run_case(c, w): return {}\n"
        "def stop(): pass\n")
    v = validate_spec(str(d))
    assert any("adapter.py" in w for w in v["warnings"])


def test_quality_target_must_be_number(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    goal = (d / "goal.yaml").read_text() + "quality_target: high\n"
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("quality_target" in p for p in v["problems"])


def test_quality_target_valid_without_quality_md(tmp_path):
    """quality_target is valid without quality.md — the quality-judge has a built-in industry rubric."""
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    (d / "quality.md").unlink()
    goal = (d / "goal.yaml").read_text() + "quality_target: 8.0\n"
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is True


def test_quality_target_range_0_10(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    goal = (d / "goal.yaml").read_text() + "quality_target: 15.0\n"
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("0-10" in p for p in v["problems"])
