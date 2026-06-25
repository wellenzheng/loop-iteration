from loop_iter.adapter_generic import resolve_harness


def test_resolve_harness_default_convention(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude/skills/foo").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("x")
    (repo / ".claude/skills/foo/SKILL.md").write_text("y")
    eval_dir = tmp_path / "eval"; eval_dir.mkdir()
    (eval_dir / "goal.yaml").write_text("threshold: 0.8\n")  # no harness key
    paths = resolve_harness(str(eval_dir), str(repo))
    assert "CLAUDE.md" in paths
    assert any(p.endswith("foo/SKILL.md") for p in paths)


def test_resolve_harness_override_replaces_default(tmp_path):
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("x")
    (repo / "prompts/p.md").write_text("y")
    eval_dir = tmp_path / "eval"; eval_dir.mkdir()
    (eval_dir / "goal.yaml").write_text("harness:\n  - prompts/**/*.md\n")
    paths = resolve_harness(str(eval_dir), str(repo))
    assert "CLAUDE.md" not in paths            # default replaced
    assert any(p.endswith("prompts/p.md") for p in paths)


def test_resolve_harness_skips_absent_default_paths(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("x")       # no AGENTS.md, no .claude/
    eval_dir = tmp_path / "eval"; eval_dir.mkdir()
    (eval_dir / "goal.yaml").write_text("threshold: 0.8\n")
    paths = resolve_harness(str(eval_dir), str(repo))
    assert paths == ["CLAUDE.md"]


from loop_iter.adapter_generic import load_run_case, run_case_default, build_agent_cmd, snapshot_harness


def test_load_run_case_none_when_absent(tmp_path):
    assert load_run_case(str(tmp_path)) is None


def test_load_run_case_loads_when_present(tmp_path):
    (tmp_path / "run_case.py").write_text(
        "def run_case(case, worktree, harness):\n"
        "    return {'case_id': case['id'], 'output': 'CUSTOM', 'trace': {}, 'error': None}\n"
    )
    fn = load_run_case(str(tmp_path))
    assert fn is not None
    r = fn({"id": "c1", "query": "q", "expected": None}, "/tmp", [])
    assert r["output"] == "CUSTOM"


def test_build_agent_cmd_defaults_and_overrides():
    assert build_agent_cmd({}) == ["claude", "-p", "--permission-mode", "bypassPermissions"]
    cmd = build_agent_cmd({"model": "claude-sonnet-4-6", "permission_mode": "acceptEdits", "extra_args": ["--foo"]})
    assert cmd == ["claude", "-p", "--permission-mode", "acceptEdits", "--model", "claude-sonnet-4-6", "--foo"]


def test_run_case_default_with_fake_agent(tmp_path, monkeypatch):
    import loop_iter.adapter_generic as ag
    fake = tmp_path / "fake.sh"
    fake.write_text("#!/bin/sh\necho \"$(cat)\" | tr a-z A-Z\n")
    fake.chmod(0o755)
    monkeypatch.setattr(ag, "build_agent_cmd", lambda config: [str(fake)])
    r = ag.run_case_default({"id": "c1", "query": "hi", "expected": None}, str(tmp_path), {})
    assert r["case_id"] == "c1"
    assert r["output"].strip() == "HI"
    assert r["error"] is None


def test_snapshot_harness_copies_listed_files(tmp_path):
    wt = tmp_path / "wt"; (wt / ".claude/skills/foo").mkdir(parents=True)
    (wt / "CLAUDE.md").write_text("root")
    (wt / ".claude/skills/foo/SKILL.md").write_text("skill")
    dest = tmp_path / "snap"
    snapshot_harness(str(wt), ["CLAUDE.md", ".claude/skills/foo/SKILL.md"], str(dest))
    assert (dest / "CLAUDE.md").read_text() == "root"
    assert (dest / ".claude/skills/foo/SKILL.md").read_text() == "skill"


from loop_iter.adapter_generic import _variant_dir, _sub, _normalize_result


def test_variant_dir_default_is_worktree(tmp_path):
    assert _variant_dir(str(tmp_path), {}) == str(tmp_path)


def test_variant_dir_with_subdir(tmp_path):
    assert _variant_dir(str(tmp_path), {"variant_subdir": "skills"}) == str(tmp_path / "skills")


def test_sub_replaces_placeholders():
    out = _sub("echo {query} in {variant_dir}",
               {"{query}": "hi", "{variant_dir}": "/wt"})
    assert out == "echo hi in /wt"


def test_normalize_result_from_str():
    r = _normalize_result("hello", "c1")
    assert r == {"case_id": "c1", "output": "hello", "trace": {}, "error": None}


def test_normalize_result_from_none():
    r = _normalize_result(None, "c1")
    assert r["output"] == "" and r["error"] is None


def test_normalize_result_from_rich_dict():
    r = _normalize_result({"output": "hi", "trace": {"x": 1}, "error": "boom"}, "c1")
    assert r == {"case_id": "c1", "output": "hi", "trace": {"x": 1}, "error": "boom"}


import sys
from loop_iter.adapter_generic import run_command_case


def test_run_command_case_substitutes_query(tmp_path):
    # cmd = [python, -c, "print uppercased argv[1]", {query}]
    cmd = [sys.executable, "-c", "import sys; print(sys.argv[1].upper())", "{query}"]
    r = run_command_case({"id": "c1", "query": "hello", "expected": None},
                         str(tmp_path), {"cmd": cmd})
    assert r["case_id"] == "c1"
    assert r["output"].strip() == "HELLO"
    assert r["error"] is None


def test_run_command_case_uses_variant_subdir(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "marker").write_text("VARIANT")
    cmd = [sys.executable, "-c", "import sys; print(open(sys.argv[1]).read())", "{variant_dir}/marker"]
    r = run_command_case({"id": "c1", "query": "q", "expected": None},
                         str(tmp_path), {"cmd": cmd, "variant_subdir": "skills"})
    assert r["output"].strip() == "VARIANT"


def test_run_command_case_never_raises_on_bad_cmd(tmp_path):
    r = run_command_case({"id": "c1", "query": "q", "expected": None},
                         str(tmp_path), {"cmd": ["/no/such/binary"], "timeout": 5})
    assert r["error"] is not None
    assert r["output"] == ""


from loop_iter.adapter_generic import run_python_import_case


def _write_entry(tmp_path, name, body):
    (tmp_path / f"{name}.py").write_text(body)
    return name


def test_run_python_import_case_str_return(tmp_path):
    name = _write_entry(tmp_path, "ent_str",
        "def run(query, variant_dir, **extra):\n    return query.upper() + '@' + variant_dir\n")
    r = run_python_import_case({"id": "c1", "query": "hi", "expected": None},
                               str(tmp_path), {"module": name, "module_path": [str(tmp_path)],
                                               "variant_subdir": "skills"})
    assert r["output"] == "HI@" + str(tmp_path / "skills")
    assert r["error"] is None


def test_run_python_import_case_rich_dict_return(tmp_path):
    name = _write_entry(tmp_path, "ent_dict",
        "def run(query, variant_dir, **extra):\n    return {'output':'ok','trace':{'k':1},'error':None}\n")
    r = run_python_import_case({"id": "c1", "query": "q", "expected": None},
                               str(tmp_path), {"module": name, "module_path": [str(tmp_path)]})
    assert r["output"] == "ok" and r["trace"] == {"k": 1}


def test_run_python_import_case_forwards_extra_kwargs(tmp_path):
    name = _write_entry(tmp_path, "ent_extra",
        "def run(query, variant_dir, channel='x', **_):\n    return channel\n")
    r = run_python_import_case({"id": "c1", "query": "q", "expected": None},
                               str(tmp_path), {"module": name, "module_path": [str(tmp_path)],
                                               "extra": {"channel": "qiyu"}})
    assert r["output"] == "qiyu"


def test_run_python_import_case_never_raises(tmp_path):
    name = _write_entry(tmp_path, "ent_boom", "def run(query, variant_dir, **_):\n    raise RuntimeError('x')\n")
    r = run_python_import_case({"id": "c1", "query": "q", "expected": None},
                               str(tmp_path), {"module": name, "module_path": [str(tmp_path)]})
    assert r["error"] is not None and r["output"] == ""


import sys, pytest
from loop_iter.adapter_generic import build_run_case


def test_factory_command_type(tmp_path):
    cmd = [sys.executable, "-c", "import sys; print(sys.argv[1].upper())", "{query}"]
    rc = build_run_case(str(tmp_path), {"type": "command", "cmd": cmd}, [])
    r = rc({"id": "c1", "query": "hi", "expected": None}, str(tmp_path))
    assert r["output"].strip() == "HI"


def test_factory_claude_p_type_returns_default_runner(tmp_path, monkeypatch):
    # environment-independent: a real `claude` may be on PATH, so stub run_case_default
    # to verify dispatch (the closure calls run_case_default with the config).
    import loop_iter.adapter_generic as ag
    captured = {}

    def _stub(case, worktree, cfg):
        captured["called"] = True
        captured["cfg"] = cfg
        return {"case_id": case["id"], "output": "", "trace": {}, "error": "stubbed"}

    monkeypatch.setattr(ag, "run_case_default", _stub)
    rc = build_run_case(str(tmp_path), {"type": "claude-p"}, [])
    r = rc({"id": "c1", "query": "q", "expected": None}, str(tmp_path))
    assert captured.get("called") is True
    assert r["case_id"] == "c1" and r["error"] is not None


def test_factory_omitted_type_with_run_case_py_uses_escape_hatch(tmp_path):
    (tmp_path / "run_case.py").write_text(
        "def run_case(case, worktree, harness):\n"
        "    return {'case_id': case['id'], 'output': 'ESCAPE', 'trace': {}, 'error': None}\n")
    rc = build_run_case(str(tmp_path), {}, ["CLAUDE.md"])
    r = rc({"id": "c1", "query": "q", "expected": None}, "/tmp")
    assert r["output"] == "ESCAPE"


def test_factory_omitted_type_without_run_case_py_falls_back_to_claude_p(tmp_path, monkeypatch):
    # environment-independent: stub run_case_default to confirm the factory falls back to
    # the claude-p default runner (not the escape hatch) when no run_case.py is present.
    import loop_iter.adapter_generic as ag
    captured = {}

    def _stub(case, worktree, cfg):
        captured["called"] = True
        return {"case_id": case["id"], "output": "", "trace": {}, "error": "stubbed"}

    monkeypatch.setattr(ag, "run_case_default", _stub)
    rc = build_run_case(str(tmp_path), {}, [])
    r = rc({"id": "c1", "query": "q", "expected": None}, str(tmp_path))
    assert captured.get("called") is True  # routed to claude-p default
    assert r["error"] is not None  # stubbed error surfaced, did not raise


def test_factory_unknown_type_raises(tmp_path):
    with pytest.raises(ValueError):
        build_run_case(str(tmp_path), {"type": "http"}, [])


from loop_iter.adapter_generic import harness_text


def test_harness_text_concatenates_with_headers_and_skips_missing(tmp_path):
    # build a fake eval dir + repo with two harness files
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("hello")
    (repo / "AGENTS.md").write_text("world")
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("harness: [CLAUDE.md, AGENTS.md, MISSING.md]\nthreshold: 0.5\nmax_rounds: 1\nweights: {gates: 1.0}\n")
    text = harness_text(str(ev), str(repo), str(repo))
    assert "### CLAUDE.md\nhello" in text
    assert "### AGENTS.md\nworld" in text
    assert "MISSING.md" not in text   # missing file skipped, no header


def test_harness_text_does_not_crash_on_binary(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_bytes(b"\xff\xfe\x00bad bytes")
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("harness: [CLAUDE.md]\nthreshold: 0.5\nmax_rounds: 1\nweights: {gates: 1.0}\n")
    text = harness_text(str(ev), str(repo), str(repo))   # must not raise
    assert "### CLAUDE.md" in text


import socket, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from loop_iter.adapter_generic import ServiceAdapter, _extract


def test_extract_dotted_path():
    assert _extract({"data": {"answer": "hi"}}, "data.answer") == "hi"
    assert _extract({"x": 1}, "x") == 1
    assert _extract({"a": {"b": {"c": 9}}}, "a.b.c") == 9
    assert _extract({"a": 1}, "missing") is None
    assert _extract({"a": 1}, "") == {"a": 1}


def _tiny_server(port, handler_cls):
    srv = HTTPServer(("127.0.0.1", port), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        import json
        try: q = json.loads(body).get("query", "")
        except Exception: q = body
        self.wfile.write(json.dumps({"data": {"answer": q.upper()}}).encode())
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def test_service_adapter_start_run_case_stop_against_real_server(tmp_path):
    port = _free_port()
    srv = _tiny_server(port, _EchoHandler)
    try:
        cfg = {
            "type": "local-service",
            "start": ["bash", "-c", f"echo started"],
            "port": port,
            "ready": f"http://localhost:{port}/",
            "endpoint": f"http://localhost:{port}/v1/chat",
            "request": '{"query":"{query}"}',
            "response_path": "data.answer",
            "timeout": 10,
        }
        ad = ServiceAdapter(cfg)
        assert ad.start(str(tmp_path)) == port
        result = ad.run_case({"id": "c1", "query": "hello"}, str(tmp_path))
        assert result["case_id"] == "c1"
        assert result["output"] == "HELLO"
        assert result["error"] is None
        ad.stop()
    finally:
        srv.shutdown()


def test_service_adapter_auto_picks_port_when_zero(tmp_path):
    cfg = {
        "type": "local-service",
        "start": ["bash", "-c", "echo x"],
        "port": 0,
        "ready": "http://localhost:{port}/",
        "endpoint": "http://localhost:{port}/v1/chat",
        "request": '{"query":"{query}"}',
        "response_path": "data.answer",
        "timeout": 3,
    }
    ad = ServiceAdapter(cfg)
    import pytest
    with pytest.raises(RuntimeError, match="not ready"):
        ad.start(str(tmp_path))
    ad.stop()


def test_service_adapter_run_case_swallows_errors(tmp_path):
    cfg = {
        "type": "local-service",
        "start": ["bash", "-c", "echo x"],
        "port": _free_port(),
        "ready": "",
        "endpoint": "http://127.0.0.1:1/v1/chat",
        "request": '{"query":"{query}"}',
        "response_path": "data.answer",
        "timeout": 2,
    }
    ad = ServiceAdapter(cfg)
    ad.start(str(tmp_path))
    result = ad.run_case({"id": "c1", "query": "hi"}, str(tmp_path))
    assert result["error"] is not None and "run_case" in result["error"]
    assert result["output"] == ""
    ad.stop()


def test_service_adapter_stop_never_raises(tmp_path):
    ad = ServiceAdapter({"type": "local-service", "start": ["bash", "-c", "echo x"],
                         "port": _free_port(), "ready": "", "endpoint": "http://127.0.0.1:1/",
                         "request": "{}", "response_path": "", "timeout": 2})
    ad.stop()
    ad.start(str(tmp_path))
    ad.stop(); ad.stop()


def test_build_run_case_returns_service_adapter_for_local_service(tmp_path):
    from loop_iter.adapter_generic import build_run_case
    ad = build_run_case(str(tmp_path), {"type": "local-service",
                         "start": ["bash", "-c", "echo x"], "port": 0, "ready": "",
                         "endpoint": "http://127.0.0.1:1/", "request": "{}",
                         "response_path": "", "timeout": 2}, [])
    assert isinstance(ad, ServiceAdapter)


def test_service_adapter_stop_kills_process_group(tmp_path):
    """stop() must kill the whole process group, not just the direct child — a start cmd that
    forks a long-running child must not leave an orphan."""
    import subprocess, time
    # start cmd: bash that backgrounds a sleep and stays alive briefly via the sleep child
    # Use a start cmd that forks a long-running child, then verify the child is gone after stop.
    cfg = {
        "type": "local-service",
        "start": ["bash", "-c", "sleep 30 & wait"],   # forks a sleep 30 child, waits on it
        "port": _free_port(),
        "ready": "",  # no ready check
        "endpoint": "http://127.0.0.1:1/",
        "request": "{}", "response_path": "", "timeout": 2,
    }
    ad = ServiceAdapter(cfg)
    ad.start(str(tmp_path))
    # the bash process + its sleep child are alive
    import os, signal
    pgid = os.getpgid(ad.proc.pid)
    ad.stop()
    # give it a moment to die
    time.sleep(0.5)
    # killing the group again should now find no live process (process group gone) -> no exception
    try:
        os.killpg(pgid, 0)  # signal 0 = existence check
        # if we reach here without exception, something in the group is still alive -> fail
        still_alive = True
    except (ProcessLookupError, PermissionError, OSError):
        still_alive = False
    assert not still_alive, "stop() left an orphan process in the service's group"
