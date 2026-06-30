# Parallel Case Running Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run eval cases concurrently with a programmatic (not agent-decided) parallelism degree read from `goal.yaml`, so 100-case rounds finish in wall-clock ≈ serial_time / N instead of serial_time.

**Architecture:** Add a `parallelism` field to `goal.yaml` (default `1` = today's serial behavior, byte-for-byte). Thread it through `cli._case_run` / `cli._baseline` into `run_cases`, which gains a `parallelism: int = 1` param. When `>1`, the entire per-case pipeline (`run_case → gates → judge`) runs on a `ThreadPoolExecutor`; when `≤1` it stays on the calling thread's serial loop. Results are returned in original case order via `executor.map`, so `scores.json` / `baseline.json` are deterministic and unchanged in shape.

**Concurrency safety principle:** thread-pool concurrency is safe for an adapter **iff the per-case `run_case` call holds no shared mutable state across calls** — a property of the adapter's implementation, not strictly of the `type` string:
- `claude-p` / `command`: independent `subprocess.run` per case → no shared state → safe.
- `local-service`: transient `httpx.post` per call → no shared client; the service process handling concurrent requests is the user's concern.
- `python-import`: safe **iff the shim builds fresh per-call state**. The maas shim (`asyncio.run(_run(...))` per call) does exactly this — `asyncio.run`'s `set_event_loop` is thread-local, each call builds + initializes a fresh agent, and `src.tools._SKILLS_DIR` is set to the same `variant_dir` by every case in a round (idempotent). Residual unknown: module-level async client caches inside `zai_adk` — but serial `asyncio.run`-per-call already produces correct results across 24 cases, which is strong evidence zai_adk does not bind a client to a closed loop. **Verify empirically with the Task 5 parallel smoke, don't assert it.**
- `custom` (`adapter.py` / `run_case.py`): `start()` writes module globals once on the main thread **before** the pool starts; `run_case()` runs concurrently and only **reads** them. Safe iff the user's `run_case` itself is thread-safe (subprocess/HTTP/pure).

`llm_client.chat` (transient `httpx.post`, reads env per call) and `run_gates` (pure) are already thread-safe, so the whole per-case body parallelizes.

**Tech Stack:** Python 3.12 stdlib `concurrent.futures.ThreadPoolExecutor`, pytest, pyyaml. No new dependencies.

---

## File Structure

- **Modify:** `scripts/loop_iter/case_runner.py` — add `parallelism` param, extract per-case body into `_run_one`, add concurrent branch. Sole concurrency site.
- **Modify:** `scripts/loop_iter/cli.py` — `_case_run` and `_baseline` read `goal.get("parallelism")` and pass it to `run_cases`.
- **Modify:** `scripts/loop_iter/validate_spec.py` — validate `parallelism` is a positive int; warn when `>1` on `python-import`.
- **Modify:** `tests/test_case_runner.py` — add concurrency + order-preservation + serial-default tests.
- **Modify:** `tests/test_validate_spec.py` — add `parallelism` validation tests.
- **Modify:** `skills/self-iterate-setup/SKILL.md`, `skills/self-iterate/SKILL.md`, `README.md` — document the `parallelism` field.

No new files. The concurrency boundary is exactly one function (`run_cases`); everything else is parameter threading and docs.

## Why `parallelism <= 1` stays on the calling thread

The serial default path MUST run `_run_one` on the calling (main) thread, not through a 1-worker `ThreadPoolExecutor`. Two reasons:

1. **Zero behavior change.** The default (`parallelism` absent or `1`) must be byte-for-byte identical to today's serial loop, including running on the main thread. Routing it through a pool — even `max_workers=1` — moves each case onto a worker thread, which is an unnecessary semantic change to the default path.
2. **Conservative default for unverified adapters.** `python-import` / `custom` are very likely thread-safe (see principle above), but that's only verified once the Task 5 parallel smoke passes. Defaulting to main-thread serial means an unverified adapter never accidentally runs concurrently.

This is why the implementation branches on `parallelism > 1` rather than unconditionally using `executor.map(max_workers=1)`.

---

### Task 1: Make `run_cases` support concurrent case execution

**Files:**
- Modify: `scripts/loop_iter/case_runner.py`
- Test: `tests/test_case_runner.py`

- [ ] **Step 1: Write failing tests for concurrency, order preservation, and serial default**

Append to `tests/test_case_runner.py`:

```python
def test_run_cases_parallel_preserves_order_and_runs_concurrently(tmp_path):
    import threading, time
    state = {"inflight": 0, "max_inflight": 0}
    lock = threading.Lock()

    def rc(case, worktree):
        with lock:
            state["inflight"] += 1
            state["max_inflight"] = max(state["max_inflight"], state["inflight"])
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
    assert state["max_inflight"] > 1
    assert out["composite"] == 1.0


def test_run_cases_serial_by_default_never_overlaps(tmp_path):
    import threading, time
    state = {"inflight": 0, "max_inflight": 0}
    lock = threading.Lock()

    def rc(case, worktree):
        with lock:
            state["inflight"] += 1
            state["max_inflight"] = max(state["max_inflight"], state["inflight"])
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
    assert state["max_inflight"] == 1
    assert [c["case_id"] for c in out["cases"]] == [c["id"] for c in cases]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_case_runner.py::test_run_cases_parallel_preserves_order_and_runs_concurrently tests/test_case_runner.py::test_run_cases_serial_by_default_never_overlaps -v`
Expected: FAIL — `TypeError: run_cases() got an unexpected keyword argument 'parallelism'` on the first test.

- [ ] **Step 3: Implement the `parallelism` param and concurrent branch**

Replace the entire body of `scripts/loop_iter/case_runner.py` with:

```python
from __future__ import annotations
import concurrent.futures
from loop_iter.gates import load_gates, run_gates
from loop_iter.judge import judge_case as _default_judge
from loop_iter.scoring import composite, gate_pass_rates, judge_means
from loop_iter.adapter_generic import ServiceAdapter

def run_cases(cases: list[dict], worktree: str,
              gates_path: str, rubric_md: str, weights: dict[str, float],
              run_case_fn, judge_case_fn=_default_judge, llm_call=None,
              parallelism: int = 1) -> dict:
    """Run every case through run_case_fn(case, worktree), then gates + judge -> RunScores.

    judge_case_fn defaults to loop_iter.judge.judge_case; tests inject a stub.
    A None judge result for a case => no dims for that case (gates-only contribution).
    llm_call is forwarded to judge_case_fn (real judge uses it; stubs ignore it).

    parallelism: max concurrent cases (default 1 = serial ON THE CALLING THREAD).
    >1 runs the per-case pipeline (run_case -> gates -> judge) on a ThreadPoolExecutor.
    Safe when the per-case run_case call holds no shared mutable state across calls:
    claude-p/command (subprocess per call), local-service (transient httpx), and
    llm_client.chat + run_gates are all thread-safe. python-import is safe when the shim
    builds fresh per-call state (the maas shim's asyncio.run per call is thread-local);
    custom adapter.py is safe when start()'s module globals are only read by run_case and
    run_case itself is thread-safe. validate_spec warns for python-import>1; smoke-test it.
    Results are returned in original case order (executor.map preserves submission order).
    """
    gates = load_gates(gates_path)
    service = run_case_fn if isinstance(run_case_fn, ServiceAdapter) else None

    def _run_one(case):
        result = (service.run_case(case, worktree) if service is not None
                  else run_case_fn(case, worktree))
        gate_results = run_gates(result, case, gates)
        judged = judge_case_fn(result, case, rubric_md, llm_call)
        return {
            "case_id": case["id"],
            "output": result.get("output", ""),
            "trace": result.get("trace") or {},
            "gates": gate_results,
            "judge": judged or [],
            "error": result.get("error"),
        }

    case_scores: list[dict] = []
    if service is not None:
        service.start(worktree)
    try:
        if parallelism and parallelism > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as ex:
                case_scores = list(ex.map(_run_one, cases))
        else:
            case_scores = [_run_one(c) for c in cases]
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

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_case_runner.py::test_run_cases_parallel_preserves_order_and_runs_concurrently tests/test_case_runner.py::test_run_cases_serial_by_default_never_overlaps -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full existing case_runner suite to confirm no regression**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_case_runner.py -v`
Expected: PASS — all 5 tests green, including `test_run_cases_wraps_service_adapter_start_once_stop_in_finally` (serial default path preserves `svc.calls == ["c1","c2","c3"]` order) and `test_run_cases_stops_service_even_on_exception`.

- [ ] **Step 6: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add scripts/loop_iter/case_runner.py tests/test_case_runner.py
git commit -m "feat: parallel case execution via parallelism param in run_cases

ThreadPoolExecutor runs the per-case pipeline (run_case->gates->judge)
concurrently when parallelism>1; parallelism<=1 stays on the calling thread
(zero behavior change for the default serial path). Results stay in case order."
```

---

### Task 2: Thread `parallelism` from `goal.yaml` through the CLI

**Files:**
- Modify: `scripts/loop_iter/cli.py:48-85` (`_case_run`), `scripts/loop_iter/cli.py:183-209` (`_baseline`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write a failing test that `case-run` passes `parallelism` from goal.yaml**

Append to `tests/test_cli.py` (adapt the existing `case-run` test's harness style; the key assertion is that a stubbed `run_cases` receives `parallelism=N`):

```python
def test_case_run_threads_parallelism_from_goal(tmp_path, monkeypatch):
    import loop_iter.cli as cli
    import loop_iter.case_runner as cr

    ev = tmp_path / "ev"; ev.mkdir()
    (ev / "goal.yaml").write_text(
        "threshold: 0.85\nmax_rounds: 4\nweights: {gates: 1.0}\nparallelism: 3\n"
        "agent: {type: claude-p}\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "rubric.md").write_text("rubric")
    (ev / "gates.py").write_text("GATES = {}\n")

    captured = {}
    def fake_run_cases(cases, worktree, gates_path, rubric_md, weights,
                       run_case_fn, judge_case_fn=None, llm_call=None, parallelism=1):
        captured["parallelism"] = parallelism
        return {"cases": [], "composite": 1.0, "gate_pass_rates": {}, "judge_means": {}}
    monkeypatch.setattr(cr, "run_cases", fake_run_cases)
    monkeypatch.setattr(cli, "run_cases", fake_run_cases, raising=False)
    # bypass the state-machine guard: no state file -> append_round path
    monkeypatch.setattr(cli, "append_round", lambda rp, out: None, raising=False)

    import argparse
    args = argparse.Namespace(eval=str(ev), worktree=str(tmp_path / "wt"),
                              run_id="r1", base=str(tmp_path), round=1)
    cli._case_run(args)
    assert captured["parallelism"] == 3
```

Note: if `tests/test_cli.py` already has a `case-run` test helper that builds the Namespace/env, mirror its exact setup instead of duplicating; the assertion `captured["parallelism"] == 3` is the contract.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_cli.py::test_case_run_threads_parallelism_from_goal -v`
Expected: FAIL — `captured["parallelism"]` is `1` (default), not `3`, because `_case_run` does not yet read `goal["parallelism"]`.

- [ ] **Step 3: Pass `parallelism` in `_case_run`**

In `scripts/loop_iter/cli.py`, in `_case_run`, change the `run_cases(...)` call (currently lines 69-71) to add the `parallelism` kwarg:

```python
    out = run_cases(cases, args.worktree, str(ev / "gates.py"),
                    _rubric_path(ev).read_text(), goal["weights"],
                    run_case_fn=rc, llm_call=llm_call,
                    parallelism=int(goal.get("parallelism") or 1))
```

- [ ] **Step 4: Pass `parallelism` in `_baseline`**

In `_baseline`, change its `run_cases(...)` call (currently lines 199-201) the same way:

```python
    out = run_cases(cases, args.base, str(ev / "gates.py"),
                    _rubric_path(ev).read_text(), goal["weights"],
                    run_case_fn=rc, llm_call=llm_call,
                    parallelism=int(goal.get("parallelism") or 1))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_cli.py::test_case_run_threads_parallelism_from_goal -v`
Expected: PASS.

- [ ] **Step 6: Run the full cli suite to confirm no regression**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS — all green.

- [ ] **Step 7: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: read goal.yaml parallelism into case-run and baseline"
```

---

### Task 3: Validate the `parallelism` field and warn on python-import

**Files:**
- Modify: `scripts/loop_iter/validate_spec.py:77-83` (after the `quality_target` block)
- Test: `tests/test_validate_spec.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_validate_spec.py`. Mirror the existing helper that writes a minimal valid spec into a tmp dir (look at the top of `tests/test_validate_spec.py` for the fixture/`_write_spec` helper and reuse it):

```python
def test_validate_spec_rejects_non_positive_parallelism(tmp_path):
    from loop_iter.validate_spec import validate_spec
    d = _write_spec(tmp_path, parallelism=0)   # reuse the existing spec-writing helper
    v = validate_spec(str(d))
    assert not v["valid"]
    assert any("parallelism must be a positive int" in p for p in v["problems"])


def test_validate_spec_warns_parallelism_with_python_import(tmp_path):
    from loop_iter.validate_spec import validate_spec
    d = _write_spec(tmp_path, parallelism=4, agent_type="python-import")
    v = validate_spec(str(d))
    assert v["valid"]   # warning, not a problem
    assert any("python-import" in w and "thread-safe" in w for w in v["warnings"])


def test_validate_spec_accepts_omitted_parallelism(tmp_path):
    from loop_iter.validate_spec import validate_spec
    d = _write_spec(tmp_path)   # no parallelism key
    v = validate_spec(str(d))
    assert v["valid"]
    assert not any("parallelism" in w for w in v["warnings"])
```

If `_write_spec` does not accept `parallelism`/`agent_type` kwargs yet, extend it minimally in the same file (add `parallelism=None` and `agent_type=None` kwargs that write the corresponding lines into `goal.yaml` when set). Keep the existing tests using it unchanged by defaulting both to `None`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_validate_spec.py -k parallelism -v`
Expected: FAIL — no `parallelism` problems/warnings are produced (the three new tests fail).

- [ ] **Step 3: Add the validation block**

In `scripts/loop_iter/validate_spec.py`, immediately after the `quality_target` block (after line 83, before the `# cases.json` comment), insert:

```python
    par = goal.get("parallelism")
    if par is not None:
        if isinstance(par, bool) or not isinstance(par, int) or par < 1:
            problems.append("goal.yaml: parallelism must be a positive int (>=1)")
        elif atype == "python-import" and par > 1:
            warnings.append("goal.yaml: parallelism>1 with agent.type=python-import runs cases "
                            "concurrently in-process; this is thread-safe only if the entry shim "
                            "builds fresh per-call state (the maas shim uses asyncio.run per call, "
                            "which is thread-local). Run `smoke` with parallelism set before relying "
                            "on it — a module-level async client cached across calls would break under "
                            "concurrency")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_validate_spec.py -k parallelism -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full validate_spec suite**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_validate_spec.py -v`
Expected: PASS — all green.

- [ ] **Step 6: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add scripts/loop_iter/validate_spec.py tests/test_validate_spec.py
git commit -m "feat: validate goal.yaml parallelism; warn on python-import"
```

---

### Task 4: Document the `parallelism` field

**Files:**
- Modify: `skills/self-iterate-setup/SKILL.md:117`
- Modify: `skills/self-iterate/SKILL.md` (near the case-run step, ~line 60-67)
- Modify: `README.md:75`

- [ ] **Step 1: Add `parallelism` to the setup skill's goal.yaml field list**

In `skills/self-iterate-setup/SKILL.md`, the line at ~117 listing goal.yaml fields (`threshold`, `max_rounds`, `regression: block`, `weights` ...) — append `parallelism` to that list and add a one-line bullet below it:

```markdown
- `parallelism` (optional, default `1`) — max concurrent cases per round. Raise it to
  speed up large case sets. Safe out-of-the-box for `claude-p`/`command`/`local-service`
  (each case is an independent subprocess / HTTP call). For `python-import` and custom
  `adapter.py` it is also safe when the entry shim builds fresh per-call state (the maas
  shim's `asyncio.run` per call is thread-local) — run `smoke` with `parallelism` set to
  confirm before relying on it.
```

- [ ] **Step 2: Mention `parallelism` in the self-iterate SKILL.md case-run step**

In `skills/self-iterate/SKILL.md`, in the baseline/case-run step description (~lines 60-67), add a short parenthetical after the case-run cli invocation:

```markdown
   *(If `goal.yaml` sets `parallelism: N>1`, the per-case pipeline runs N-wide on a
   thread pool — programmatic concurrency, not agent-decided. Safe out-of-the-box for
   `claude-p`/`command`/`local-service`; for `python-import`/custom it is safe when the
   shim builds fresh per-call state — run `smoke` with it set to confirm.)*
```

- [ ] **Step 3: Add `parallelism` to the README goal.yaml fields line**

In `README.md:75`, the line `goal.yaml     # threshold, weights, regression, optional agent:/harness: overrides` — change to:

```
  goal.yaml     # threshold, weights, regression, parallelism, optional agent:/harness: overrides
```

- [ ] **Step 4: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add skills/self-iterate-setup/SKILL.md skills/self-iterate/SKILL.md README.md
git commit -m "docs: document goal.yaml parallelism field"
```

---

### Task 5: Full-suite regression + dogfood sanity check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest -q`
Expected: PASS — all tests green (the integration tests that spawn real services are skipped/offline by default; if any require network, they should be unaffected since `parallelism` defaults to `1`).

- [ ] **Step 2: Validate the maas goal spec still passes (no behavior change)**

Run: `cd /Users/zhengweijun/rag/maas-customer-agent && /Users/zhengweijun/agent/loop-iteration/.venv/bin/python /Users/zhengweijun/agent/loop-iteration/scripts/loop_iter/cli.py validate-spec --eval .self-iterate/skill-coverage`
Expected: `{"valid": true, ...}` — `parallelism` is absent so it serializes exactly as before.

- [ ] **Step 3: Empirically verify python-import concurrency on maas (replaces armchair claim)**

The whole "python-import is thread-safe under concurrency" conclusion rests on inference. Verify it for real by running the maas shim's `build_run_case` through `run_cases(parallelism=4)` on a few cases. `smoke` only runs one case, so use a throwaway script. Run in the maas venv (it has `zai_adk`) with the plugin's `scripts/` on `PYTHONPATH`:

```bash
cd /Users/zhengweijun/rag/maas-customer-agent
PYTHONPATH=/Users/zhengweijun/agent/loop-iteration/scripts:. \
.venv/bin/python -c "
import json, yaml
from loop_iter.case_runner import run_cases
from loop_iter.adapter_generic import build_run_case, resolve_harness
from loop_iter.llm_client import chat as llm_call
ev='.self-iterate/skill-coverage'
goal=yaml.safe_load(open(f'{ev}/goal.yaml').read())
cases=json.loads(open(f'{ev}/cases.json').read_text())[:6]
harness=resolve_harness(ev,'.')
rc=build_run_case(ev, goal.get('agent',{}), harness)
out=run_cases(cases,'.',f'{ev}/gates.py',open(f'{ev}/rubric.md').read(),
              goal['weights'], run_case_fn=rc, llm_call=llm_call, parallelism=4)
errs=[c['error'] for c in out['cases'] if c['error']]
print('cases:',len(out['cases']),'errors:',len(errs),'composite:',out['composite'])
for e in errs[:5]: print('  ERR:',e[:200])
"
```

Expected: `errors: 0` and `composite` is a number. **Failure modes to watch for** (proof that zai_adk does cache a loop-bound client, which would mean python-import needs a process pool after all): any error string containing `Event loop is closed`, `attached to a different loop`, `There is no current event loop in thread`, or `RuntimeError`. If any appear, STOP: record which case/error, and the plan's conclusion is wrong — python-import would then need the process-pool backend, not the thread pool. If `errors: 0`, the thread-pool approach is confirmed for maas.

This step mutates no state (no `--run-id`, no `scores.json` write) — it only calls `run_cases` in memory.

---

## Self-Review

**1. Spec coverage.** The user asked for (a) parallel case running → Task 1; (b) programmatic, not agent-decided → `parallelism` is read from `goal.yaml` and applied by `run_cases` in code, never by the maker/agent — Tasks 1+2; (c) a goal field for the parallelism degree → `parallelism` in `goal.yaml`, validated in Task 3, documented in Task 4. All three requirements covered. No gap.

**2. Placeholder scan.** No TBD/TODO/"add error handling". Every code step shows the full code. The only "adapt the existing helper" language is in Task 2 Step 1 and Task 3 Step 1, where the plan reuses an existing test helper whose exact name lives in the target file — the instruction tells the engineer exactly what contract to assert (`captured["parallelism"] == 3`) and to mirror the existing test's setup. Acceptable.

**3. Type/name consistency.** `parallelism: int = 1` param on `run_cases` (Task 1) is passed as `parallelism=int(goal.get("parallelism") or 1)` in both `_case_run` and `_baseline` (Task 2) — names match. `validate_spec` reads `goal.get("parallelism")` (Task 3) — same key. `_run_one` is defined and used within `run_cases` only. `ServiceAdapter` lifecycle (`start`/`stop` on main thread, `run_case` parallelizable) is preserved exactly. No signature drift.

**4. Concurrency-safety audit (the real risk).** Safety = "no shared mutable state across `run_case` calls."
- `claude-p`/`command`: `subprocess.run` per case, no shared Python state — safe. ✓
- `local-service`: `httpx.post` via module-level transient client per call, no shared client — safe; the service process handling concurrency is the user's concern, gated by opt-in `parallelism`. ✓
- `llm_client.chat`: `httpx.post` module-level, reads env each call, no shared mutable state — safe. ✓
- `run_gates`: pure over `(result, case)`; user gate fns are called independently per case — safe. ✓
- `python-import`: the maas shim uses `asyncio.run` per call (thread-local loop) + builds a fresh agent per call; `src.tools._SKILLS_DIR` is set to the same `variant_dir` by every case in a round (idempotent). Safe **unless** `zai_adk` caches a loop-bound async client at module level — serial `asyncio.run`-per-call already working across 24 cases is strong evidence it doesn't, but this is **verified empirically by Task 5 Step 3, not asserted**. ✓ (conditional on smoke)
- `custom` (`adapter.py`/`run_case.py`): `start()` writes module globals once before the pool; `run_case()` reads them + does per-case work — safe iff the user's `run_case` is itself thread-safe. ✓ (conditional)
- `ServiceAdapter.start/stop`: run once on the main thread outside the pool — unchanged. ✓
- Order: `executor.map` preserves submission order → `case_scores` deterministic → `scores.json` shape identical. ✓
</parameter>
</invoke>
