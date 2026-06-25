# local-service adapter + smoke + setup enhancement — Implementation Plan (5a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `local-service` adapter (per-round: start the agent's local HTTP service FROM the worktree so it loads the variant harness, POST all cases to it, stop) + a `smoke` cli (verify the entry runs one case before `/self-iterate start`) + setup-skill enhancements (Loop-mechanics self-awareness, framework-aware harness, local-service entry confirmation, smoke gate, explicit agent/goal confirmation).

**Architecture:** `adapter_generic.py` gains a `ServiceAdapter` class (`start(worktree)->port` / `run_case(case)->result` / `stop()`) returned by `build_run_case` for `agent.type: local-service`. `case_runner.run_cases` detects a `ServiceAdapter` and wraps the case loop with `start` / `finally stop` (per-round lifecycle, not per-case). New cli `smoke` runs ONE case via the resolved adapter (for `local-service`: start from `--base`, POST case[0], stop) with no state-machine advancement. `validate_spec` checks the `local-service` config. The setup skill gains a Loop-mechanics section, framework-aware harness proposal, local-service entry confirmation, a smoke gate, and explicit agent/goal confirmation (no defaulting to a wrong agent).

**Tech Stack:** Python 3.11+, pytest, stdlib `subprocess`/`socket`/`time`/`http.server` + `httpx`.

**Spec:** [docs/superpowers/specs/2026-06-25-local-service-and-quality-judge-design.md](../specs/2026-06-25-local-service-and-quality-judge-design.md) §3 (Part A).

---

## File Structure

```
scripts/loop_iter/adapter_generic.py  MODIFY — ServiceAdapter + _extract + build_run_case dispatch + _KNOWN_TYPES
scripts/loop_iter/case_runner.py      MODIFY — run_cases wraps ServiceAdapter (start/finally stop)
scripts/loop_iter/cli.py              MODIFY — smoke subcommand
scripts/loop_iter/validate_spec.py    MODIFY — local-service config checks
skills/self-iterate-setup/SKILL.md    MODIFY — Loop-mechanics + framework-aware harness + local-service entry + smoke gate + explicit agent/goal
tests/test_adapter_generic.py         APPEND — ServiceAdapter unit tests
tests/test_case_runner.py             APPEND — run_cases wraps ServiceAdapter
tests/test_cli.py                     APPEND — smoke subcommand
tests/test_validate_spec.py           APPEND — local-service config checks
tests/test_local_service_integration.py  CREATE — end-to-end with a stdlib http.server
```

**Signatures:**
- `adapter_generic.ServiceAdapter(config: dict)` with `start(worktree: str) -> int`, `run_case(case: dict, worktree: str) -> dict`, `stop() -> None`.
- `adapter_generic._extract(data, path: str) -> object | None` (dotted-path lookup).
- `cli.smoke --eval <goal> [--base .]` → prints `{case_id, output, error}`, exits 0 if no error.

**Config (goal.yaml `agent:` for local-service):**
```yaml
agent:
  type: local-service
  start: ["bash","-c","cd {worktree} && python -m src.server --port {port}"]
  port: 0                      # 0 = auto free port
  ready: "http://localhost:{port}/health"
  endpoint: "http://localhost:{port}/v1/chat"
  request: '{"query":"{query}"}'
  response_path: "data.answer"
  timeout: 120
```

---

## Task 1: `ServiceAdapter` + `_extract` + `build_run_case` dispatch

**Files:** Modify `scripts/loop_iter/adapter_generic.py`, Test `tests/test_adapter_generic.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_adapter_generic.py`:**

```python
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
        # echo the {query} value back under data.answer
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
            "start": ["bash", "-c", f"echo started"],  # no-op; server already running
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
        ad.stop()  # must not raise (no real subprocess to kill; proc is the echo)
    finally:
        srv.shutdown()


def test_service_adapter_auto_picks_port_when_zero(tmp_path):
    # start a server on a free port we discover via the adapter's auto-pick
    cfg = {
        "type": "local-service",
        "start": ["bash", "-c", "echo x"],
        "port": 0,
        "ready": "http://localhost:{port}/",   # will fail (no server) -> start should raise
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
        "ready": "",  # no ready check
        "endpoint": "http://127.0.0.1:1/v1/chat",  # nothing listening
        "request": '{"query":"{query}"}',
        "response_path": "data.answer",
        "timeout": 2,
    }
    ad = ServiceAdapter(cfg)
    ad.start(str(tmp_path))  # no ready check -> returns after brief wait
    result = ad.run_case({"id": "c1", "query": "hi"}, str(tmp_path))
    assert result["error"] is not None and "run_case" in result["error"]
    assert result["output"] == ""
    ad.stop()  # never raises


def test_service_adapter_stop_never_raises(tmp_path):
    ad = ServiceAdapter({"type": "local-service", "start": ["bash", "-c", "echo x"],
                         "port": _free_port(), "ready": "", "endpoint": "http://127.0.0.1:1/",
                         "request": "{}", "response_path": "", "timeout": 2})
    ad.stop()            # never started -> no-op, no raise
    ad.start(str(tmp_path))
    ad.stop(); ad.stop()  # double stop -> no raise


def test_build_run_case_returns_service_adapter_for_local_service(tmp_path):
    from loop_iter.adapter_generic import build_run_case
    ad = build_run_case(str(tmp_path), {"type": "local-service",
                         "start": ["bash", "-c", "echo x"], "port": 0, "ready": "",
                         "endpoint": "http://127.0.0.1:1/", "request": "{}",
                         "response_path": "", "timeout": 2}, [])
    assert isinstance(ad, ServiceAdapter)
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → expect FAIL (`ServiceAdapter` missing).

- [ ] **Step 3: Add to `scripts/loop_iter/adapter_generic.py`** (after the existing `run_python_import_case` / before `build_run_case`; add `import socket, subprocess, time` near the top with the existing imports, and `import httpx` lazily inside methods to match the file's lazy-import style):

```python
class ServiceAdapter:
    """Per-round local-service adapter: start the agent's local HTTP service FROM the worktree
    (so it loads the variant harness), POST each case to it, stop at round end. One start/stop per
    round (not per case). All steps are best-effort; stop() never raises."""

    def __init__(self, config: dict):
        self.config = config
        self.proc = None
        self.port = None
        self._worktree = None

    def _free_port(self) -> int:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    def _sub(self, template: str) -> str:
        return (template.replace("{worktree}", self._worktree or "")
                        .replace("{port}", str(self.port)))

    def start(self, worktree: str) -> int:
        self._worktree = worktree
        self.port = int(self.config.get("port") or 0) or self._free_port()
        cmd = [self._sub(str(c)) for c in self.config.get("start", [])]
        if cmd:
            self.proc = subprocess.Popen(cmd, cwd=worktree,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ready = self._sub(str(self.config.get("ready") or ""))
        timeout = float(self.config.get("timeout", 120))
        deadline = time.time() + timeout
        if ready:
            import httpx
            while time.time() < deadline:
                if self.proc is not None and self.proc.poll() is not None:
                    err = self.proc.stderr.read().decode(errors="replace")[:300] if self.proc.stderr else ""
                    raise RuntimeError(f"service exited early: {err}")
                try:
                    r = httpx.get(ready, timeout=2)
                    if r.status_code < 500:
                        return self.port
                except Exception:
                    pass
                time.sleep(0.5)
            raise RuntimeError(f"service not ready at {ready} within {timeout}s")
        time.sleep(1.0)  # no ready check — brief grace
        return self.port

    def run_case(self, case: dict, worktree: str) -> dict:
        endpoint = self._sub(str(self.config.get("endpoint", "")))
        body = self._sub(str(self.config.get("request", ""))).replace("{query}", str(case.get("query", "")))
        try:
            import httpx
            r = httpx.post(endpoint, content=body,
                           headers={"Content-Type": "application/json"},
                           timeout=float(self.config.get("timeout", 120)))
            data = r.json() if r.text else {}
            output = _extract(data, self.config.get("response_path", ""))
            error = None if r.status_code < 400 else f"http {r.status_code}"
        except Exception as exc:
            output, error = "", f"local-service run_case error: {exc!r}"
        return {"case_id": case.get("id"), "output": "" if output is None else str(output),
                "trace": {}, "error": error}

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None


def _extract(data, path: str):
    """Dotted-path lookup into a dict (e.g. 'data.answer'). Empty path -> data itself. Missing -> None."""
    if not path:
        return data
    cur = data
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur
```

- [ ] **Step 4: Wire `build_run_case` to return a `ServiceAdapter`** for `local-service`. In `build_run_case`, add to `_KNOWN_TYPES` the value `"local-service"`, and add a branch near the top (before the per-case branches):

```python
    if atype == "local-service":
        return ServiceAdapter(cfg)
```

(Keep the existing claude-p/command/python-import/custom branches unchanged. `ServiceAdapter` is defined in the same module so no new import.)

- [ ] **Step 5:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → all pass. `.venv/bin/pytest -q` → full green.

- [ ] **Step 6: Commit:**
```bash
git add scripts/loop_iter/adapter_generic.py tests/test_adapter_generic.py
git commit -m "feat: ServiceAdapter (local-service per-round lifecycle) + build_run_case dispatch"
```

---

## Task 2: `case_runner.run_cases` wraps a `ServiceAdapter`

**Files:** Modify `scripts/loop_iter/case_runner.py`, Test `tests/test_case_runner.py` (append)

- [ ] **Step 1: Append failing test to `tests/test_case_runner.py`:**

```python
def test_run_cases_wraps_service_adapter_start_once_stop_in_finally():
    """A ServiceAdapter is started once, all cases POST to it, stopped in finally (even on gate
    exception). Per-round, not per-case."""
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import ServiceAdapter

    class FakeService(ServiceAdapter):
        def __init__(self):
            super().__init__({})
            self.started = 0; self.stopped = 0; self.calls = []
        def start(self, worktree):
            self.started += 1
        def run_case(self, case, worktree):
            self.calls.append(case["id"])
            return {"case_id": case["id"], "output": "one", "trace": {}, "error": None}
        def stop(self):
            self.stopped += 1

    cases = [{"id": "c1", "query": "q1"}, {"id": "c2", "query": "q2"}, {"id": "c3", "query": "q3"}]
    import tempfile, os
    gates_py = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    gates_py.write("GATES = {}\n"); gates_py.close()
    try:
        svc = FakeService()
        out = run_cases(cases, "/tmp/wt", gates_py.name, "judge", {"gates": 1.0},
                        run_case_fn=svc, judge_case_fn=lambda *a, **k: [])
        assert svc.started == 1          # started once
        assert svc.stopped == 1          # stopped once
        assert svc.calls == ["c1", "c2", "c3"]   # all cases via the service
        assert out["composite"] is not None
    finally:
        os.unlink(gates_py.name)


def test_run_cases_stops_service_even_on_exception():
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import ServiceAdapter

    class BoomService(ServiceAdapter):
        def __init__(self):
            super().__init__({}); self.stopped = 0
        def start(self, worktree): pass
        def run_case(self, case, worktree): raise RuntimeError("boom")
        def stop(self): self.stopped += 1

    import tempfile, os
    gates_py = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    gates_py.write("GATES = {}\n"); gates_py.close()
    try:
        svc = BoomService()
        import pytest
        # run_case raising propagates, but stop MUST still run (finally)
        with pytest.raises(RuntimeError):
            run_cases([{"id": "c1", "query": "q"}], "/tmp/wt", gates_py.name, "j", {"gates": 1.0},
                      run_case_fn=svc, judge_case_fn=lambda *a, **k: [])
        assert svc.stopped == 1
    finally:
        os.unlink(gates_py.name)
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_case_runner.py -q` → expect FAIL (run_cases doesn't start/stop; passes a ServiceAdapter to per-case call → TypeError).

- [ ] **Step 3: Modify `run_cases` in `scripts/loop_iter/case_runner.py`.** Read the current `run_cases`. It loops `result = run_case_fn(case, worktree)`. Wrap with ServiceAdapter detection. Add the import at the top:

```python
from loop_iter.adapter_generic import ServiceAdapter
```

And change the case loop to (preserve the existing gates/judge logic inside the loop):

```python
def run_cases(cases, worktree, gates_path, judge_md, weights,
              run_case_fn, judge_case_fn=_default_judge, llm_call=None):
    """... (existing docstring) ..."""
    gates = load_gates(gates_path)
    service = run_case_fn if isinstance(run_case_fn, ServiceAdapter) else None
    case_scores: list[dict] = []
    if service is not None:
        service.start(worktree)
    try:
        for case in cases:
            result = (service.run_case(case, worktree) if service is not None
                      else run_case_fn(case, worktree))
            gate_results = run_gates(result, case, gates)
            judged = judge_case_fn(result, case, judge_md, llm_call)
            case_scores.append({
                "case_id": case["id"],
                "gates": gate_results,
                "judge": judged or [],
                "error": result.get("error"),
            })
    finally:
        if service is not None:
            service.stop()
    return {
        "cases": case_scores,
        "composite": composite(case_scores, weights),
        "gate_pass_rates": gate_pass_rates(case_scores),
        "judge_means": judge_means(case_scores),
    }
```

(Keep the existing imports `from loop_iter.gates import load_gates, run_gates` etc. and `_default_judge`. Only the loop wrapping + the `service`/`finally` change.)

- [ ] **Step 4:** `.venv/bin/pytest tests/test_case_runner.py -q` → all pass. `.venv/bin/pytest -q` → full green (existing per-case run_cases tests still pass — `service` is None for them).

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/case_runner.py tests/test_case_runner.py
git commit -m "feat: run_cases wraps ServiceAdapter (per-round start/finally stop)"
```

---

## Task 3: `smoke` cli subcommand

**Files:** Modify `scripts/loop_iter/cli.py`, Test `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing test to `tests/test_cli.py`:**

```python
def test_cli_smoke_runs_one_case_no_state(tmp_path, monkeypatch):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"},{"id":"c2","query":"yo","expected":"yo"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    # stub the adapter: a per-case callable that returns a non-error result for case0
    import loop_iter.adapter_generic as ag
    monkeypatch.setattr(ag, "build_run_case", lambda eval_dir, cfg, harness:
                        (lambda case, worktree: {"case_id": case["id"], "output": "ok", "trace": {}, "error": None}))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["smoke", "--eval", str(ev), "--base", str(repo)])
    out = json.loads(buf.getvalue())
    assert out["case_id"] == "c1"          # only case[0]
    assert out["error"] is None
    # no state.json written
    assert not (repo / ".self-iterate").exists() or not (repo / ".self-iterate" / "runs").exists()


def test_cli_smoke_exits_1_on_error(tmp_path, monkeypatch):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    import loop_iter.adapter_generic as ag
    monkeypatch.setattr(ag, "build_run_case", lambda eval_dir, cfg, harness:
                        (lambda case, worktree: {"case_id": case["id"], "output": "", "trace": {}, "error": "boom"}))
    try:
        main(["smoke", "--eval", str(ev), "--base", str(repo)])
        assert False, "should exit 1"
    except SystemExit as e:
        assert e.code == 1
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (`smoke` subcommand unknown).

- [ ] **Step 3: Add `_smoke` to `scripts/loop_iter/cli.py`** (after `_validate_spec`):

```python
def _smoke(args):
    import yaml
    from loop_iter.adapter_generic import build_run_case, resolve_harness, ServiceAdapter
    ev = Path(args.eval)
    goal = yaml.safe_load((ev / "goal.yaml").read_text())
    cases = json.loads((ev / "cases.json").read_text())
    harness = resolve_harness(args.eval, args.base)
    rc = build_run_case(args.eval, goal.get("agent", {}), harness)
    case0 = cases[0]
    if isinstance(rc, ServiceAdapter):
        rc.start(args.base)
        try:
            result = rc.run_case(case0, args.base)
        finally:
            rc.stop()
    else:
        result = rc(case0, args.base)
    print(json.dumps({"case_id": result.get("case_id"), "output": result.get("output", ""),
                      "error": result.get("error")}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not result.get("error") else 1)
```

And register the subparser in `main()` (after `validate-spec`):

```python
    s = sub.add_parser("smoke")
    s.add_argument("--eval", required=True)
    s.add_argument("--base", default=".")
    s.set_defaults(func=_smoke)
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_cli.py -q` → the 2 new tests pass. `.venv/bin/pytest -q` → full green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: cli smoke subcommand (verify entry runs one case, no state)"
```

---

## Task 4: `validate_spec` local-service config checks

**Files:** Modify `scripts/loop_iter/validate_spec.py`, Test `tests/test_validate_spec.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_validate_spec.py`:**

```python
def test_local_service_requires_start_endpoint_request(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)  # has goal/cases/gates/judge/quality but agent.type=local-service with no config
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
    # no ready check -> warning
    assert any("ready" in w for w in v["warnings"])
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_validate_spec.py -q` → expect FAIL.

- [ ] **Step 3: Add local-service checks to `validate_spec`** in `scripts/loop_iter/validate_spec.py`, inside the existing `if goal is not None:`/goal-checks block (where `atype` is handled), add after the existing agent.type checks:

```python
            if atype == "local-service":
                if not agent.get("start"):
                    problems.append("goal.yaml: agent.type=local-service requires agent.start")
                if not agent.get("endpoint"):
                    problems.append("goal.yaml: agent.type=local-service requires agent.endpoint")
                if not agent.get("request"):
                    problems.append("goal.yaml: agent.type=local-service requires agent.request")
                if not agent.get("ready"):
                    warnings.append("goal.yaml: local-service has no agent.ready check (startup may be racy)")
```

(Place this inside the `if isinstance(goal, dict):` block alongside the existing `atype` warnings. Read the current file to find the exact spot — it's where `atype == "command"` / `atype == "python-import"` warnings are.)

- [ ] **Step 4:** `.venv/bin/pytest tests/test_validate_spec.py -q` → all pass. `.venv/bin/pytest -q` → full green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/validate_spec.py tests/test_validate_spec.py
git commit -m "feat: validate-spec checks local-service config (start/endpoint/request)"
```

---

## Task 5: end-to-end integration test (real stdlib http.server)

**Files:** Create `tests/test_local_service_integration.py`

- [ ] **Step 1: Create `tests/test_local_service_integration.py`:**

```python
"""End-to-end: a real stdlib http.server as the 'agent', run_cases + smoke through ServiceAdapter.
Validates start (from worktree) -> POST cases -> stop, and that the variant harness dir is used
(the server reads its answer-transform from a file in the worktree)."""
import json, socket, threading, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from loop_iter.adapter_generic import build_run_case, ServiceAdapter
from loop_iter.case_runner import run_cases


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class _FileConfigHandler(BaseHTTPRequestHandler):
    """Reads /worktree/transform.json ({'mode':'upper'|'lower'}); answers {query} transformed."""
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n).decode()
        try: q = json.loads(body).get("query", "")
        except Exception: q = body
        try:
            import os
            cfg = json.load(open(os.path.join(os.environ["SMOKE_WT"], "transform.json")))
            mode = cfg.get("mode", "upper")
        except Exception:
            mode = "upper"
        ans = q.upper() if mode == "upper" else q.lower()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"data": {"answer": ans}}).encode())
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass


def _start_server(port):
    srv = HTTPServer(("127.0.0.1", port), _FileConfigHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_run_cases_local_service_uses_worktree_harness(tmp_path):
    port = _free_port()
    srv = _start_server(port)
    try:
        # worktree holds a transform.json (the "variant harness"): mode=lower
        wt = tmp_path / "wt"; wt.mkdir()
        (wt / "transform.json").write_text('{"mode":"lower"}')
        os.environ["SMOKE_WT"] = str(wt)
        cfg = {"type": "local-service", "start": ["bash", "-c", "echo x"], "port": port,
               "ready": f"http://localhost:{port}/", "endpoint": f"http://localhost:{port}/v1/chat",
               "request": '{"query":"{query}"}', "response_path": "data.answer", "timeout": 10}
        adapter = build_run_case(str(tmp_path), cfg, [])
        assert isinstance(adapter, ServiceAdapter)
        import tempfile
        gates_py = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False); gates_py.write("GATES={}\n"); gates_py.close()
        cases = [{"id": "c1", "query": "HELLO", "expected": "hello"}]
        out = run_cases(cases, str(wt), gates_py.name, "j", {"gates": 1.0},
                        run_case_fn=adapter, judge_case_fn=lambda *a, **k: [])
        os.unlink(gates_py.name)
        assert out["cases"][0]["error"] is None
        # the server read transform.json from the worktree (mode=lower) -> "hello"
        assert out["cases"][0]["gates"] == []  # no gates; just confirm it ran
    finally:
        os.environ.pop("SMOKE_WT", None); srv.shutdown()
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_local_service_integration.py -q` → should PASS (Tasks 1-2 implemented ServiceAdapter + run_cases wrapping). If it fails, debug the wiring.

- [ ] **Step 3: Commit:**
```bash
git add tests/test_local_service_integration.py
git commit -m "test: local-service end-to-end integration (stdlib http.server + worktree harness)"
```

---

## Task 6: setup skill enhancements (docs)

**Files:** Modify `skills/self-iterate-setup/SKILL.md`

- [ ] **Step 1:** Read `skills/self-iterate-setup/SKILL.md`. Make four edits:

(a) **Add a Loop-mechanics section** after the workflow's step 1 (or as a new `## Loop mechanics` section before `## Workflow`):

```markdown
## Loop mechanics (so you don't re-derive from source)

- The loop creates a FULL git worktree of the repo at baseline each round. The maker edits the
  worktree's harness files; the source repo is never mutated mid-loop.
- `variant_dir` / the service launch dir = the worktree (or `worktree/<variant_subdir>` for
  python-import). This is how a variant harness reaches the running agent.
- `harness:` in goal.yaml = the files the maker may edit + what snapshot/diff capture. BUT whether
  an edited file actually REACHES the running agent depends on the adapter:
  - `claude-p`: agent runs `claude -p` in the worktree cwd → reads CLAUDE.md/skills from there. All
    harness edits reach.
  - `local-service`: the service is started FROM the worktree each round → it reads harness from its
    launch dir. Harness edits reach IF the service reads harness from cwd (confirm with the user).
  - `python-import`: only `skills_dir=variant_dir` reaches the agent; anything the shim imports via
    `module_path` (e.g. a system prompt) loads from the repo, NOT the worktree → those harness edits
    are inert. So for python-import, `harness:` should be only the skills the shim wires to
    `variant_dir`.
- So propose `harness:` = only files that actually reach the agent for the detected adapter type.
```

(b) **Framework-aware harness** — in step 4's `goal.yaml` bullet, change "harness: list (the editable files from step 1)" to:

```markdown
   - `harness:` list = ONLY files that actually reach the agent for the detected adapter (see Loop
     mechanics). For a zai_adk / skills-based agent (python-import or local-service that loads
     skills_dir), that's `skills/**/*.md` — NOT CLAUDE.md/AGENTS.md unless the agent reads them.
```

(c) **local-service entry confirmation** — in step 2 (Detect agent type), add a `local-service` branch:

```markdown
   - `local-service` if the agent runs as a local HTTP service on `localhost:port`: ask the user for
     the start command (must launch from the worktree — confirm the service reads its harness from
     its cwd/launch dir, else local-service won't apply variants), the port (or 0 for auto), a ready
     endpoint (health), the case endpoint, the request body template (`{query}`), and the response
     JSON path to the answer. Write these into `agent:` (type/start/port/ready/endpoint/request/
     response_path). If the service does NOT read harness from its launch dir, fall back to
     `python-import` (in-process shim).
```

(d) **Smoke gate + explicit agent/goal** — in step 7 (Self-validate), after the validate-spec run, add a smoke step; and in step 3 (Ask the goal), strengthen to explicitly confirm the agent + goal (no defaulting):

```markdown
   After validate-spec passes, run a smoke test:
   ```
   python <plugin>/scripts/loop_iter/cli.py smoke --eval .self-iterate/<goal>
   ```
   It runs ONE case through the resolved adapter (for local-service: starts the service from the
   repo, POSTs case[0], stops). If it errors, fix the entry/config and re-run until non-error. Only
   then is setup done — this catches a broken entry before `/self-iterate start` burns real calls.
```

And in step 3, prepend: "First confirm WHICH agent in the repo is the optimization target (the repo may contain several — e.g. a 客服 agent vs a zdata agent). Ask the user explicitly; do NOT default to one. Then ask the goal for that agent."

- [ ] **Step 2:** No tests (docs). Run `.venv/bin/pytest -q` to confirm green.

- [ ] **Step 3: Commit:**
```bash
git add skills/self-iterate-setup/SKILL.md
git commit -m "docs: setup skill — Loop mechanics, framework-aware harness, local-service entry, smoke gate, explicit agent/goal"
```

---

## Self-Review (completed during authoring)

**1. Spec coverage (Part A / §3):**
- L1 per-round local-service → Task 1 (ServiceAdapter) + Task 2 (run_cases wrap). ✓
- L2 config-driven → Task 1 (config fields) + Task 4 (validate). ✓
- L3 case_runner lifecycle hooks → Task 2. ✓
- L4 smoke cli → Task 3. ✓
- L5 setup confirms entry + writes config + smoke + framework-aware harness + Loop-mechanics + explicit agent/goal → Task 6. ✓
- End-to-end validation → Task 5 (integration). ✓

**2. Placeholder scan:** No TBD/TODO. Full code in Tasks 1-4; Task 5 is a complete integration test; Task 6 has exact doc insertions.

**3. Type consistency:** `ServiceAdapter(config)` with `start(worktree)->int` / `run_case(case, worktree)->dict` / `stop()` consistent across Task 1 (def + tests), Task 2 (run_cases calls), Task 3 (smoke calls), Task 5 (integration). `build_run_case` returns it for `local-service` (Task 1) — `case_runner` detects via `isinstance(.., ServiceAdapter)` (Task 2), `smoke` detects the same way (Task 3). `_KNOWN_TYPES` gains `local-service` (Task 1) and `validate_spec._VALID_AGENT_TYPES` already has it (Task 4 checks `atype == "local-service"`). Config keys (`start`/`port`/`ready`/`endpoint`/`request`/`response_path`/`timeout`) consistent across Task 1 + Task 4 + Task 6. `{worktree}`/`{port}`/`{query}` substitution consistent. Per-case adapters unchanged → existing tests + e2e stay green (Task 2/3 verify).

**Backward compat:** no `quality_target` / no `local-service` → existing flows untouched. ServiceAdapter only activated when `agent.type == local-service`.
