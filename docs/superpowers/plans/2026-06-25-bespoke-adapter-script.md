# bespoke-protocol adapter script — Implementation Plan (5a.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an agent with a bespoke protocol (SSE / JWT / custom event format — e.g. maas `/v1/chat`) run on方案 A (per-round: start the real service FROM the worktree, call it, stop) via a **per-agent script in `.self-iterate/<goal>/adapter.py`** that the setup skill generates — instead of bloating the plugin's `local-service` config with every protocol variant.

**Architecture:** A new `adapter.py` escape hatch (alongside the existing per-case `run_case.py`): it defines `start(worktree)` / `run_case(case, worktree)` / `stop()`. The plugin's `load_adapter(eval_dir)` loads it and wraps it in a `_UserScriptAdapter` (a `ServiceAdapter` subclass), so `case_runner.run_cases` and `cli.smoke` already handle it via the existing `isinstance(.., ServiceAdapter)` path — **no change to run_cases/smoke**. `build_run_case` prefers `adapter.py` (per-round lifecycle) over `run_case.py` (per-case) over the claude-p default. The bespoke protocol (start cmd, JWT, SSE parsing) lives entirely in the agent's `adapter.py`, setup-authored by reading the agent's code. Fully backward-compatible (no adapter.py → unchanged).

**Tech Stack:** Python 3.11+, pytest, stdlib `importlib`.

**Spec basis:** [local-service + quality-judge spec](2026-06-25-local-service-and-quality-judge-design.md) §3, extended per the 2026-06-25 dogfood finding (maas `/v1/chat` is SSE-only + bespoke encoder + JWT; per-agent protocol belongs in `.self-iterate/`).

---

## File Structure

```
scripts/loop_iter/adapter_generic.py  MODIFY — _UserScriptAdapter + load_adapter + build_run_case prefers adapter.py
scripts/loop_iter/validate_spec.py    MODIFY — optional adapter.py check (start/run_case/stop)
skills/self-iterate-setup/SKILL.md    MODIFY — bespoke protocol → generate adapter.py (investigate-first)
tests/test_adapter_generic.py         APPEND — _UserScriptAdapter / load_adapter / build_run_case dispatch
tests/test_validate_spec.py           APPEND — adapter.py checks
tests/test_bespoke_adapter_integration.py  CREATE — end-to-end SSE-style agent + adapter.py
```

**Signatures:**
- `adapter_generic._UserScriptAdapter(mod)` — `ServiceAdapter` subclass; `start(worktree)` → `mod.start(worktree)`, `run_case(case, worktree)` → `mod.run_case(case, worktree)`, `stop()` → `mod.stop()`.
- `adapter_generic.load_adapter(eval_dir: str) -> _UserScriptAdapter | None` — loads `eval_dir/adapter.py`, requires `start`/`run_case`/`stop`, returns the wrapper (None if no adapter.py).
- `build_run_case` precedence (custom/omitted type): `adapter.py` (lifecycle) → `run_case.py` (per-case) → claude-p default.

**adapter.py contract (the agent-specific script):**
```python
# .self-iterate/<goal>/adapter.py — bespoke protocol (SSE/JWT/...). setup generates this.
def start(worktree):
    """Start the real service FROM the worktree (so it loads the variant harness). Return a port
    or stash state for run_case. Called ONCE per round."""
def run_case(case, worktree):
    """Call the service for one case (e.g. POST /v1/chat with JWT, parse SSE). Return
    {case_id, output, trace, error}. Never raises (error field)."""
def stop():
    """Stop the service. Called ONCE per round (finally). Never raises."""
```

---

## Task 1: `_UserScriptAdapter` + `load_adapter` + `build_run_case` dispatch

**Files:** Modify `scripts/loop_iter/adapter_generic.py`, Test `tests/test_adapter_generic.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_adapter_generic.py`:**

```python
def test_load_adapter_returns_wrapper_for_adapter_py(tmp_path):
    from loop_iter.adapter_generic import load_adapter, _UserScriptAdapter, ServiceAdapter
    ev = tmp_path / "g"; ev.mkdir()
    (ev / "adapter.py").write_text(
        "def start(worktree):\n    return 9999\n"
        "def run_case(case, worktree):\n    return {'case_id': case['id'], 'output': 'x', 'trace': {}, 'error': None}\n"
        "def stop():\n    pass\n")
    ad = load_adapter(str(ev))
    assert isinstance(ad, _UserScriptAdapter)
    assert isinstance(ad, ServiceAdapter)          # isinstance -> run_cases/smoke handle it
    assert ad.start("/tmp/wt") == 9999
    assert ad.run_case({"id": "c1"}, "/tmp/wt")["output"] == "x"
    ad.stop()  # no raise


def test_load_adapter_none_when_no_adapter_py(tmp_path):
    from loop_iter.adapter_generic import load_adapter
    ev = tmp_path / "g"; ev.mkdir()
    assert load_adapter(str(ev)) is None


def test_load_adapter_raises_if_missing_lifecycle_fn(tmp_path):
    import pytest
    from loop_iter.adapter_generic import load_adapter
    ev = tmp_path / "g"; ev.mkdir()
    (ev / "adapter.py").write_text(
        "def start(worktree):\n    pass\n"
        "def run_case(case, worktree):\n    return {}\n")  # no stop()
    with pytest.raises(ValueError, match="stop"):
        load_adapter(str(ev))


def test_build_run_case_prefers_adapter_py_over_run_case_py(tmp_path):
    """If both adapter.py (lifecycle) and run_case.py (per-case) exist, adapter.py wins."""
    from loop_iter.adapter_generic import build_run_case, _UserScriptAdapter
    ev = tmp_path / "g"; ev.mkdir()
    (ev / "adapter.py").write_text(
        "def start(w): return 1\n"
        "def run_case(c, w): return {'case_id': c['id'], 'output': 'adapter', 'trace': {}, 'error': None}\n"
        "def stop(): pass\n")
    (ev / "run_case.py").write_text(
        "def run_case(case, worktree, harness):\n    return {'case_id': case['id'], 'output': 'percase', 'trace': {}, 'error': None}\n")
    rc = build_run_case(str(ev), {"type": "custom"}, ["CLAUDE.md"])
    assert isinstance(rc, _UserScriptAdapter)
    assert rc.run_case({"id": "c1"}, "/tmp/wt")["output"] == "adapter"


def test_build_run_case_falls_back_to_run_case_py_when_no_adapter(tmp_path):
    """No adapter.py -> per-case run_case.py (current behavior unchanged)."""
    from loop_iter.adapter_generic import build_run_case, _UserScriptAdapter
    ev = tmp_path / "g"; ev.mkdir()
    (ev / "run_case.py").write_text(
        "def run_case(case, worktree, harness):\n    return {'case_id': case['id'], 'output': 'percase', 'trace': {}, 'error': None}\n")
    rc = build_run_case(str(ev), {"type": "custom"}, ["CLAUDE.md"])
    assert not isinstance(rc, _UserScriptAdapter)     # a per-case callable
    assert rc({"id": "c1"}, "/tmp/wt")["output"] == "percase"


def test_user_script_adapter_runs_through_run_cases_per_round(tmp_path):
    """End-to-end via run_cases: start once, run_case per case, stop once (finally)."""
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import build_run_case
    ev = tmp_path / "g"; ev.mkdir()
    (ev / "adapter.py").write_text(
        "STATE = {'started': 0, 'stopped': 0, 'calls': []}\n"
        "def start(w):\n    STATE['started'] += 1\n    return 8000\n"
        "def run_case(c, w):\n    STATE['calls'].append(c['id']); return {'case_id': c['id'], 'output': 'ans', 'trace': {}, 'error': None}\n"
        "def stop():\n    STATE['stopped'] += 1\n")
    import tempfile, os
    gates_py = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False); gates_py.write("GATES={}\n"); gates_py.close()
    try:
        rc = build_run_case(str(ev), {"type": "custom"}, [])
        import importlib.util
        spec = importlib.util.spec_from_file_location("_state", ev / "adapter.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        out = run_cases([{"id": "c1", "query": "q"}, {"id": "c2", "query": "q"}], "/tmp/wt",
                        gates_py.name, "j", {"gates": 1.0}, run_case_fn=rc, judge_case_fn=lambda *a, **k: [])
        assert mod.STATE["started"] == 1
        assert mod.STATE["stopped"] == 1
        assert mod.STATE["calls"] == ["c1", "c2"]
        assert out["cases"][0]["output"] == "ans"
    finally:
        os.unlink(gates_py.name)
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → expect FAIL (`load_adapter`/`_UserScriptAdapter` missing).

- [ ] **Step 3: Add to `scripts/loop_iter/adapter_generic.py`** (after the `ServiceAdapter` class + `_extract`, before `build_run_case`):

```python
class _UserScriptAdapter(ServiceAdapter):
    """Wraps a .self-iterate/<goal>/adapter.py that defines start/run_case/stop — a per-round
    lifecycle adapter for bespoke protocols (SSE/JWT/custom event format). The plugin calls
    start once per round, run_case per case, stop in finally — same as the built-in ServiceAdapter.
    The bespoke protocol lives entirely in the agent's adapter.py (setup-authored)."""

    def __init__(self, mod):
        super().__init__({})
        self._mod = mod

    def start(self, worktree: str):
        return self._mod.start(worktree)

    def run_case(self, case: dict, worktree: str) -> dict:
        return self._mod.run_case(case, worktree)

    def stop(self) -> None:
        self._mod.stop()


def load_adapter(eval_dir: str):
    """Load .self-iterate/<goal>/adapter.py as a _UserScriptAdapter if it defines start/run_case/stop
    (per-round lifecycle for bespoke protocols). Returns None if no adapter.py. Raises ValueError if
    adapter.py exists but lacks start/run_case/stop."""
    p = Path(eval_dir, "adapter.py")
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_user_adapter_{p.stat().st_mtime_ns}", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    for fn in ("start", "run_case", "stop"):
        if not hasattr(mod, fn):
            raise ValueError(f"{p} must define start(worktree), run_case(case, worktree), stop()")
    return _UserScriptAdapter(mod)
```

(`importlib.util` is already imported at the top of adapter_generic.py — verify; if not, add it. `Path` is imported.)

- [ ] **Step 4: Wire `build_run_case` to prefer `adapter.py`.** Read the current `build_run_case`. In the custom/omitted branch (currently: `user_rc = load_run_case(eval_dir); if user_rc is not None: return lambda...`), prepend the adapter.py check:

```python
    # atype is None or "custom": prefer adapter.py (per-round lifecycle), then run_case.py (per-case)
    adapter = load_adapter(eval_dir)
    if adapter is not None:
        return adapter
    user_rc = load_run_case(eval_dir)
    if user_rc is not None:
        return lambda case, worktree: user_rc(case, worktree, harness)
    return lambda case, worktree: run_case_default(case, worktree, cfg)
```

(Keep the existing claude-p/command/python-import branches above this unchanged. The custom/omitted tail gains the `load_adapter` check first.)

- [ ] **Step 5:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → all pass. `.venv/bin/pytest -q` → full green (existing run_case.py / claude-p paths unchanged).

- [ ] **Step 6: Commit:**
```bash
git add scripts/loop_iter/adapter_generic.py tests/test_adapter_generic.py
git commit -m "feat: adapter.py escape hatch (bespoke-protocol per-round lifecycle via _UserScriptAdapter)"
```

---

## Task 2: `validate_spec` optional adapter.py check

**Files:** Modify `scripts/loop_iter/validate_spec.py`, Test `tests/test_validate_spec.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_validate_spec.py`:**

```python
def test_adapter_py_optional_no_warning(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    # no adapter.py -> no problem, no warning about it
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
    """adapter.py present -> informational warning (bespoke protocol; lifecycle not statically checked)."""
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    (d / "adapter.py").write_text(
        "def start(w): pass\n"
        "def run_case(c, w): return {}\n"
        "def stop(): pass\n")
    v = validate_spec(str(d))
    assert any("adapter.py" in w for w in v["warnings"])
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_validate_spec.py -q` → expect FAIL.

- [ ] **Step 3: Add an adapter.py check to `validate_spec`** in `scripts/loop_iter/validate_spec.py`. After the quality.md block (near the end, before the return), add:

```python
    # adapter.py (optional bespoke-protocol lifecycle script)
    adapter_path = d / "adapter.py"
    if adapter_path.exists():
        warnings.append("adapter.py present: bespoke-protocol lifecycle script "
                         "(start/run_case/stop) — not statically checked; run `smoke` to verify")
```

(Read the current file to place this alongside the other optional-file checks, before `return {...}`.)

- [ ] **Step 4:** `.venv/bin/pytest tests/test_validate_spec.py -q` → all pass. `.venv/bin/pytest -q` → full green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/validate_spec.py tests/test_validate_spec.py
git commit -m "feat: validate-spec notes optional adapter.py (bespoke lifecycle script)"
```

---

## Task 3: setup skill — bespoke protocol → generate adapter.py

**Files:** Modify `skills/self-iterate-setup/SKILL.md`

- [ ] **Step 1: Read `skills/self-iterate-setup/SKILL.md`.** In step 2 (Detect agent type), the `local-service` bullet handles simple JSON endpoints. Add guidance for bespoke protocols (SSE/JWT/custom event format) that the built-in `local-service` can't handle: generate an `adapter.py`. Append a new bullet after the `local-service` bullet:

```markdown
   - **bespoke protocol (SSE / JWT / custom event format)** — if the agent's endpoint streams (SSE)
     or needs auth/custom parsing that the declarative `local-service` config can't express (e.g.
     maas `/v1/chat` is SSE-only with a custom event encoder + JWT): INVESTIGATE the agent's code
     (the route handler, the SSE encoder, the auth module) and WRITE a `.self-iterate/<goal>/adapter.py`
     defining `start(worktree)` (launch the real service FROM the worktree so it loads the variant
     harness), `run_case(case, worktree)` (call the endpoint with the right auth + parse the bespoke
     response into `{output, error}`), and `stop()` (kill the service). Set `agent.type: custom`.
     The bespoke protocol lives in this per-agent script — not in the plugin. Then smoke-test it.
```

And in step 5 (Write the spec), note adapter.py is written when the protocol is bespoke:

```markdown
5. **Write the spec** to `.self-iterate/<goal>/` (goal.yaml, cases.json, gates.py, judge.md,
   quality.md, and the entry shim / run_case.py / adapter.py if the agent type needs one).
```

- [ ] **Step 2:** No tests (docs). Run `.venv/bin/pytest -q` to confirm green.

- [ ] **Step 3: Commit:**
```bash
git add skills/self-iterate-setup/SKILL.md
git commit -m "docs: setup skill generates adapter.py for bespoke protocols (SSE/JWT)"
```

---

## Task 4: end-to-end integration test (bespoke SSE-style agent + adapter.py)

**Files:** Create `tests/test_bespoke_adapter_integration.py`

- [ ] **Step 1: Create `tests/test_bespoke_adapter_integration.py`:**

```python
"""End-to-end: a bespoke SSE-style agent run via an agent-authored adapter.py (start/run_case/stop).
Validates that a per-agent script in .self-iterate/ drives the per-round lifecycle (start from
worktree -> call the bespoke endpoint per case -> stop), applying the variant harness."""
import json, socket, threading, os, tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from loop_iter.adapter_generic import build_run_case, _UserScriptAdapter
from loop_iter.case_runner import run_cases


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class _SSEHandler(BaseHTTPRequestHandler):
    """A bespoke SSE endpoint: reads <WT>/mode.txt ('upper'|'lower'), emits 2 SSE data events
    then [DONE]. Each data event is JSON {"chunk": "<text>"}. The adapter must concatenate."""
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n).decode()
        try: q = json.loads(body).get("query", "")
        except Exception: q = body
        try:
            mode = open(os.path.join(os.environ["BESPOKE_WT"], "mode.txt")).read().strip()
        except Exception:
            mode = "upper"
        out = q.upper() if mode == "upper" else q.lower()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        # bespoke SSE: split the answer into 2 chunks
        half = len(out) // 2 or 1
        for chunk in (out[:half], out[half:]):
            self.wfile.write(f"data: {json.dumps({'chunk': chunk})}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
    def log_message(self, *a): pass


def _start_server(port):
    srv = HTTPServer(("127.0.0.1", port), _SSEHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


ADAPTER_PY = (
    "import json, os\n"
    "_port = None\n"
    "def start(worktree):\n"
    "    global _port\n"
    "    _port = int(os.environ['BESPOKE_PORT'])\n"
    "    return _port\n"
    "def run_case(case, worktree):\n"
    "    import urllib.request\n"
    "    body = json.dumps({'query': case.get('query','')}).encode()\n"
    "    try:\n"
    "        r = urllib.request.urlopen(f'http://127.0.0.1:{_port}/v1/chat', data=body, timeout=10)\n"
    "        text = r.read().decode()\n"
    "        out = ''\n"
    "        for line in text.splitlines():\n"
    "            if line.startswith('data: ') and line != 'data: [DONE]':\n"
    "                out += json.loads(line[6:])['chunk']\n"
    "        return {'case_id': case['id'], 'output': out, 'trace': {}, 'error': None}\n"
    "    except Exception as e:\n"
    "        return {'case_id': case['id'], 'output': '', 'trace': {}, 'error': f'adapter: {e!r}'}\n"
    "def stop():\n"
    "    pass\n"
)


def test_bespoke_adapter_py_drives_per_round_lifecycle(tmp_path):
    port = _free_port()
    srv = _start_server(port)
    try:
        # worktree holds mode.txt (the "variant harness"): mode=lower
        wt = tmp_path / "wt"; wt.mkdir()
        (wt / "mode.txt").write_text("lower")
        os.environ["BESPOKE_WT"] = str(wt); os.environ["BESPOKE_PORT"] = str(port)
        ev = tmp_path / "g"; ev.mkdir()
        (ev / "adapter.py").write_text(ADAPTER_PY)
        rc = build_run_case(str(ev), {"type": "custom"}, [])
        assert isinstance(rc, _UserScriptAdapter)
        gpath = str(tmp_path / "gates.py")
        with open(gpath, "w") as f:
            f.write("def lower(result, case):\n    return {'passed': result['output'] == case['query'].lower()}\nGATES={'lower':lower}\n")
        cases = [{"id": "c1", "query": "HELLO"}, {"id": "c2", "query": "WORLD"}]
        out = run_cases(cases, str(wt), gpath, "j", {"gates": 1.0},
                        run_case_fn=rc, judge_case_fn=lambda *a, **k: [])
        # the bespoke SSE was parsed + the variant harness (mode=lower from worktree) was applied
        assert out["cases"][0]["error"] is None
        assert out["cases"][0]["output"] == "hello"   # HELLO lowercased + reassembled from 2 SSE chunks
        assert out["cases"][1]["output"] == "world"
        assert out["gate_pass_rates"]["lower"] == 1.0
    finally:
        os.environ.pop("BESPOKE_WT", None); os.environ.pop("BESPOKE_PORT", None); srv.shutdown()
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_bespoke_adapter_integration.py -q` → should PASS (Task 1 implemented _UserScriptAdapter + build_run_case dispatch; run_cases already wraps ServiceAdapter). If it fails, debug.

- [ ] **Step 3: Commit:**
```bash
git add tests/test_bespoke_adapter_integration.py
git commit -m "test: bespoke adapter.py end-to-end (SSE-style agent + per-round lifecycle)"
```

---

## Self-Review (completed during authoring)

**1. Spec coverage:**
- bespoke protocol → adapter.py in .self-iterate/ → Task 1 (`_UserScriptAdapter` + `load_adapter` + `build_run_case` precedence) + Task 3 (setup generates it). ✓
- per-round lifecycle via user script (方案 A) → Task 1 (isinstance ServiceAdapter → run_cases wraps) + Task 4 (integration). ✓
- backward compat (no adapter.py → run_case.py / claude-p unchanged) → Task 1 (precedence: adapter.py → run_case.py → default). ✓
- validate → Task 2. ✓

**2. Placeholder scan:** No TBD/TODO. Full code in every step. ADAPTER_PY in Task 4 is complete.

**3. Type consistency:** `_UserScriptAdapter(mod)` is a `ServiceAdapter` subclass (isinstance True) → run_cases/smoke handle it without change (Task 1 verifies isinstance). `load_adapter(eval_dir) -> _UserScriptAdapter | None`. `build_run_case` precedence: adapter.py → run_case.py → claude-p (Task 1 tests all three). adapter.py contract: `start(worktree)` / `run_case(case, worktree)` / `stop()` — consistent across Task 1 (tests), Task 3 (setup doc), Task 4 (integration ADAPTER_PY). `run_case` in adapter.py takes `(case, worktree)` (no harness_paths — the service reads harness from worktree itself), distinct from per-case `run_case.py`'s `(case, worktree, harness)` — documented. No run_cases/smoke change (isinstance path covers it).

**Backward compat:** no adapter.py + no run_case.py → claude-p default; run_case.py only → per-case (current); adapter.py → per-round lifecycle (new). All existing tests + e2e unchanged.
