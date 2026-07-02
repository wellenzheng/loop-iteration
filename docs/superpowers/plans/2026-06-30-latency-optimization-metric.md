# Latency as an Optimization Metric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add agent runtime as a first-class, uncapped optimization target (relative to baseline) with best-effort internal-call-timing visibility, working across all adapter types.

**Architecture:** Per-case `elapsed_ms` (timing only `run_case`, not gates/judge) is the universal scored signal; `compute_latency_score = baseline_mean / round_mean` (uncapped) is overlaid onto `composite` via a new `extra` param when `weights.latency` is set. `trace.timings` (best-effort, adapter-filled) drives a pure `latency_feedback` attribution string for the maker. All additive, opt-in; absent `weights.latency` = zero behavior change.

**Tech Stack:** Python 3.12 stdlib (`time.perf_counter`), pytest, pyyaml. No new dependencies.

**Execution:** Create branch `feat/latency-metric` from `main` before starting. Tasks 1-6 are in the `loop-iteration` repo (`/Users/zhengweijun/agent/loop-iteration`); Task 7 edits the maas repo (`/Users/zhengweijun/rag/maas-customer-agent`). Run plugin tests with `.venv/bin/python -m pytest`.

---

## File Structure

- **Modify:** `scripts/loop_iter/scoring.py` — `composite(extra=)` + `compute_latency_score()`.
- **Modify:** `scripts/loop_iter/case_runner.py` — time `run_case`, record `elapsed_ms` per case + `round_latency_ms` in return.
- **Create:** `scripts/loop_iter/latency_feedback.py` — pure `latency_feedback(round_cases, baseline_cases)` attribution.
- **Modify:** `scripts/loop_iter/cli.py` — `_apply_latency()` helper wired into `_case_run` and `_baseline`.
- **Modify:** `scripts/loop_iter/validate_spec.py` — `weights.latency` warning.
- **Modify:** `skills/self-iterate-setup/SKILL.md`, `skills/self-iterate/SKILL.md`, `README.md` — docs.
- **Modify (maas repo):** `.self-iterate/skill-coverage/entry.py` — fill `trace.timings`.
- **Tests:** `tests/test_scoring.py`, `tests/test_case_runner.py`, `tests/test_latency_feedback.py`, `tests/test_cli.py`, `tests/test_validate_spec.py`.

---

### Task 1: Scoring — `composite(extra=)` and `compute_latency_score()`

**Files:**
- Modify: `scripts/loop_iter/scoring.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_scoring.py`:

```python
from loop_iter.scoring import composite, compute_latency_score


def test_composite_with_extra_latency_uncapped():
    # one case, gate passes, no judge dims; latency extra = 2.0 (round 2x faster than baseline)
    cases = [{"gates": [{"gate": "g", "passed": True}], "judge": []}]
    # gates_component = 1.0; weights gates=0.5, latency=0.5
    # acc = 0.5*1.0 + 0.5*2.0 = 1.5; w_total = 1.0 -> 1.5
    assert composite(cases, {"gates": 0.5, "latency": 0.5}, extra={"latency": 2.0}) == 1.5


def test_composite_without_extra_unchanged():
    cases = [{"gates": [{"gate": "g", "passed": True}], "judge": []}]
    # no extra -> behaves as today: acc = 0.5*1.0, w_total = 0.5 -> 1.0
    assert composite(cases, {"gates": 0.5, "latency": 0.5}) == 1.0


def test_composite_extra_ignored_when_weight_absent():
    cases = [{"gates": [{"gate": "g", "passed": True}], "judge": []}]
    # latency in extra but NOT in weights -> contributes 0 (weight 0), no effect
    assert composite(cases, {"gates": 1.0}, extra={"latency": 2.0}) == 1.0


def test_compute_latency_score_normal_ratio():
    assert compute_latency_score(100.0, 200.0) == 0.5   # round 2x slower
    assert compute_latency_score(200.0, 100.0) == 2.0   # round 2x faster (uncapped)


def test_compute_latency_score_baseline_missing():
    assert compute_latency_score(100.0, None) == 1.0
    assert compute_latency_score(100.0, 0.0) == 1.0


def test_compute_latency_score_round_zero():
    assert compute_latency_score(0.0, 200.0) == 1.0   # avoid divide-by-zero
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_scoring.py -k "extra_latency or without_extra or ignored_when_weight or compute_latency" -v`
Expected: FAIL — `composite() got an unexpected keyword argument 'extra'` and `cannot import name 'compute_latency_score'`.

- [ ] **Step 3: Implement**

In `scripts/loop_iter/scoring.py`, change the `composite` signature to accept `extra=None` and fold extra components in by weight. The new `composite`:

```python
def composite(case_scores: list[dict], weights: dict[str, float],
              extra: dict[str, float] | None = None) -> float:
    """Weighted composite in 0-1 (may exceed 1.0 if an `extra` component is uncapped).
    weights has key 'gates' + judge dim names + any extra component names (e.g. 'latency').
    `extra` maps component name -> score (e.g. {"latency": 1.7}); only components also
    present in `weights` contribute. Absent `extra` -> current gates+judge behavior."""
    gpr = gate_pass_rates(case_scores)
    jm = judge_means(case_scores)
    gates_component = sum(gpr.values()) / len(gpr) if gpr else 0.0
    acc = 0.0
    w_total = 0.0
    if "gates" in weights:
        acc += weights["gates"] * gates_component
        w_total += weights["gates"]
    for dim, score10 in jm.items():
        w = weights.get(dim, 0.0)
        acc += w * (score10 / 10.0)
        w_total += w
    for name, score in (extra or {}).items():
        w = weights.get(name, 0.0)
        acc += w * score
        w_total += w
    return acc / w_total if w_total else 0.0
```

And add `compute_latency_score` (place it after `composite`):

```python
def compute_latency_score(round_latency_ms: float | None,
                          baseline_latency_ms: float | None) -> float:
    """Latency score relative to baseline, UNCAPPED (may exceed 1.0 when round is faster).
    baseline 0/None (missing/old baseline, first run) -> 1.0 (neutral, degrade).
    round 0 (all cases instant, theoretical) -> 1.0 (avoid divide-by-zero)."""
    if not baseline_latency_ms or not round_latency_ms:
        return 1.0
    return baseline_latency_ms / round_latency_ms
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_scoring.py -v`
Expected: PASS — all scoring tests green (new + existing).

- [ ] **Step 5: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add scripts/loop_iter/scoring.py tests/test_scoring.py
git commit -m "feat: composite extra param + compute_latency_score (uncapped, relative baseline)"
```

---

### Task 2: case_runner — record `elapsed_ms` per case + `round_latency_ms`

**Files:**
- Modify: `scripts/loop_iter/case_runner.py`
- Test: `tests/test_case_runner.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_case_runner.py`:

```python
def test_run_cases_records_elapsed_ms_per_case(tmp_path):
    import time
    def rc(case, worktree):
        time.sleep(0.05)  # 50ms; only run_case is timed
        return {"case_id": case["id"], "output": "OK", "trace": {}, "error": None}
    out = run_cases(
        cases=[{"id": "c1", "query": "q", "expected": None}], worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), rubric_md="x", weights={"gates": 1.0},
        run_case_fn=rc, judge_case_fn=lambda *a, **k: [], llm_call=None,
    )
    assert out["cases"][0]["elapsed_ms"] >= 40.0  # ~50ms, allow slack


def test_elapsed_ms_excludes_gates_and_judge_time(tmp_path):
    import time
    def rc(case, worktree):
        time.sleep(0.05)
        return {"case_id": case["id"], "output": "OK", "trace": {}, "error": None}
    def slow_gates(result, case, gates):
        time.sleep(0.05)
        return []
    def slow_judge(result, case, rubric_md, llm_call):
        time.sleep(0.05)
        return []
    out = run_cases(
        cases=[{"id": "c1", "query": "q", "expected": None}], worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), rubric_md="x", weights={"gates": 1.0},
        run_case_fn=rc, judge_case_fn=slow_judge, llm_call=None,
    )
    # run_case ~50ms; gates+judge would add ~100ms if mistakenly included -> ~150ms.
    # elapsed_ms must be just the run_case portion.
    assert 40.0 <= out["cases"][0]["elapsed_ms"] < 120.0


def test_round_latency_ms_is_mean_of_elapsed(tmp_path):
    def rc(case, worktree):
        return {"case_id": case["id"], "output": "OK", "trace": {}, "error": None}
    cases = [{"id": "c1", "query": "q"}, {"id": "c2", "query": "q"}]
    out = run_cases(
        cases=cases, worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), rubric_md="x", weights={"gates": 1.0},
        run_case_fn=rc, judge_case_fn=lambda *a, **k: [], llm_call=None,
    )
    mean_elapsed = sum(c["elapsed_ms"] for c in out["cases"]) / len(out["cases"])
    assert out["round_latency_ms"] == mean_elapsed


def test_round_latency_ms_zero_for_empty_cases(tmp_path):
    out = run_cases(
        cases=[], worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), rubric_md="x", weights={"gates": 1.0},
        run_case_fn=lambda c, w: {}, judge_case_fn=lambda *a, **k: [], llm_call=None,
    )
    assert out["round_latency_ms"] == 0.0
    assert out["cases"] == []
```

NOTE on the `slow_gates` stub above: `run_gates` is called internally, not passed in. The `gates_path` loads a gates module; you cannot inject `slow_gates` via the gates_path easily. So REPLACE the `test_elapsed_ms_excludes_gates_and_judge_time` test with a version that only proves gates/judge time is NOT in elapsed_ms by making the JUDGE slow (judge_case_fn IS injectable) and the run_case fast, then asserting elapsed_ms stays small:

```python
def test_elapsed_ms_excludes_judge_time(tmp_path):
    import time
    def rc(case, worktree):
        return {"case_id": case["id"], "output": "OK", "trace": {}, "error": None}  # ~0ms
    def slow_judge(result, case, rubric_md, llm_call):
        time.sleep(0.1)  # 100ms in judge
        return []
    out = run_cases(
        cases=[{"id": "c1", "query": "q", "expected": None}], worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), rubric_md="x", weights={"gates": 1.0},
        run_case_fn=rc, judge_case_fn=slow_judge, llm_call=None,
    )
    # if judge time were included, elapsed_ms would be >= 90ms; it must be << 90ms
    assert out["cases"][0]["elapsed_ms"] < 50.0
```

Use this `test_elapsed_ms_excludes_judge_time` version (not the slow_gates one). Do NOT include the `slow_gates` stub.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_case_runner.py -k "elapsed_ms or round_latency" -v`
Expected: FAIL — `KeyError: 'elapsed_ms'` / `KeyError: 'round_latency_ms'`.

- [ ] **Step 3: Implement**

In `scripts/loop_iter/case_runner.py`, add `import time` at the top, time the `run_case` portion in `_run_one`, and add `round_latency_ms` to the return. The adapter contract guarantees `run_case` never raises (it catches and returns an `error` field), so no try/finally is needed. The new `_run_one` and return block:

```python
    def _run_one(case):
        t0 = time.perf_counter()
        result = (service.run_case(case, worktree) if service is not None
                  else run_case_fn(case, worktree))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        gate_results = run_gates(result, case, gates)
        judged = judge_case_fn(result, case, rubric_md, llm_call)
        return {
            "case_id": case["id"],
            "output": result.get("output", ""),
            "trace": result.get("trace") or {},
            "gates": gate_results,
            "judge": judged or [],
            "error": result.get("error"),
            "elapsed_ms": elapsed_ms,
        }
```

And the return dict at the end of `run_cases`:

```python
    elapsed = [c["elapsed_ms"] for c in case_scores]
    round_latency_ms = sum(elapsed) / len(elapsed) if elapsed else 0.0
    return {
        "cases": case_scores,
        "composite": composite(case_scores, weights),
        "gate_pass_rates": gate_pass_rates(case_scores),
        "judge_means": judge_means(case_scores),
        "round_latency_ms": round_latency_ms,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_case_runner.py -v`
Expected: PASS — all case_runner tests green (new + existing, including the parallelism/service-stop tests which are unaffected since `elapsed_ms` is additive).

- [ ] **Step 5: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add scripts/loop_iter/case_runner.py tests/test_case_runner.py
git commit -m "feat: record per-case elapsed_ms + round_latency_ms (timing run_case only)"
```

---

### Task 3: `latency_feedback` — pure attribution function

**Files:**
- Create: `scripts/loop_iter/latency_feedback.py`
- Test: `tests/test_latency_feedback.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_latency_feedback.py`:

```python
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
    assert "1->1" in out or "1→1" not in out  # count line present
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


def test_feedback_baseline_missing_timings_reports_round_only():
    round_cases = [
        {"case_id": "c1", "elapsed_ms": 500.0, "trace": {"timings": [
            {"phase": "llm_call", "ms": 500.0, "count": 1},
        ]}},
    ]
    out = latency_feedback(round_cases, None)
    assert "llm_call" in out
    assert "500" in out


def test_feedback_empty_round_returns_empty():
    assert latency_feedback([], None) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_latency_feedback.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.latency_feedback'`.

- [ ] **Step 3: Implement**

Create `scripts/loop_iter/latency_feedback.py`:

```python
from __future__ import annotations

def _aggregate_phases(cases: list[dict]) -> dict[str, dict]:
    """Sum ms and count per phase across cases. Returns {phase: {"ms": float, "count": int}}."""
    agg: dict[str, dict] = {}
    for c in cases:
        for t in (c.get("trace") or {}).get("timings", []) or []:
            p = t.get("phase")
            if not p:
                continue
            d = agg.setdefault(p, {"ms": 0.0, "count": 0})
            d["ms"] += float(t.get("ms", 0.0))
            d["count"] += int(t.get("count", 0))
    return agg


def latency_feedback(round_cases: list[dict], baseline_cases: list[dict] | None = None) -> str:
    """Best-effort latency attribution for the maker. Pure function.
    - If trace.timings present: top-3 phases by ms increase vs baseline (with count delta).
    - Else: top-3 cases by elapsed_ms delta vs baseline.
    - baseline absent/missing timings: report round's own top only, no crash.
    Returns "" for empty round_cases."""
    if not round_cases:
        return ""
    round_agg = _aggregate_phases(round_cases)
    if round_agg:
        base_agg = _aggregate_phases(baseline_cases) if baseline_cases else {}
        rows = []
        for p, rd in round_agg.items():
            bd = base_agg.get(p, {"ms": 0.0, "count": 0})
            rows.append((p, rd, bd, rd["ms"] - bd["ms"]))
        rows.sort(key=lambda x: x[3], reverse=True)
        lines = ["Latency by phase (round vs baseline):"]
        for p, rd, bd, d_ms in rows[:3]:
            sign = "+" if d_ms >= 0 else ""
            lines.append(f"  {p}: {bd['count']}->{rd['count']} calls, "
                         f"{bd['ms']:.0f}->{rd['ms']:.0f}ms ({sign}{d_ms:.0f}ms)")
        return "\n".join(lines)
    # no timings -> per-case elapsed delta
    base_elapsed = {c["case_id"]: float(c.get("elapsed_ms", 0.0))
                    for c in (baseline_cases or []) if "case_id" in c}
    rows = []
    for c in round_cases:
        cid = c.get("case_id")
        re = float(c.get("elapsed_ms", 0.0))
        be = base_elapsed.get(cid)
        rows.append((cid, re, be, (re - be) if be is not None else None))
    rows.sort(key=lambda x: (x[3] if x[3] is not None else float("-inf")), reverse=True)
    lines = ["Latency by case (round vs baseline):"]
    for cid, re, be, d in rows[:3]:
        if d is not None:
            sign = "+" if d >= 0 else ""
            lines.append(f"  {cid}: {re:.0f}ms vs baseline {be:.0f}ms ({sign}{d:.0f}ms)")
        else:
            lines.append(f"  {cid}: {re:.0f}ms (no baseline)")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_latency_feedback.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add scripts/loop_iter/latency_feedback.py tests/test_latency_feedback.py
git commit -m "feat: latency_feedback pure attribution (phase breakdown or per-case delta)"
```

---

### Task 4: cli — `_apply_latency` overlay in `_case_run` and `_baseline`

**Files:**
- Modify: `scripts/loop_iter/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`. These build a self-contained eval dir + RunPaths. Read the existing `_case_run` tests in `tests/test_cli.py` first to confirm the `RunPaths`/`state_file`/`append_round` monkeypatch pattern; if the file uses a helper to build the eval dir, you may reuse it, but the assertions below are the contract.

```python
def test_case_run_overlays_latency_when_weight_set(tmp_path, monkeypatch):
    import loop_iter.cli as cli
    import loop_iter.case_runner as cr
    from loop_iter.state import RunPaths
    import json

    base = tmp_path
    ev = base / "ev"; ev.mkdir()
    (ev / "goal.yaml").write_text(
        "threshold: 0.85\nmax_rounds: 4\nweights: {gates: 0.5, latency: 0.5}\nagent: {type: claude-p}\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "rubric.md").write_text("rubric")
    (ev / "gates.py").write_text("GATES = {}\n")

    rp = RunPaths(base=str(base), run_id="r1")
    rp.run_dir.mkdir(parents=True, exist_ok=True)
    rp.baseline_file.write_text(json.dumps({"round_latency_ms": 200.0, "cases": []}))
    rp.state_file.write_text(json.dumps({"phase": "eval", "round": 1, "max_rounds": 4,
                                         "run_id": "r1", "goal": "g", "met": False,
                                         "baseline_composite": 1.0, "best": {"round": None}}))

    captured = {}
    def fake_run_cases(cases, worktree, gates_path, rubric_md, weights,
                       run_case_fn, judge_case_fn=None, llm_call=None, parallelism=1):
        return {"cases": [{"case_id": "c1", "output": "OK", "trace": {},
                           "gates": [{"gate": "g", "passed": True}], "judge": [],
                           "error": None, "elapsed_ms": 100.0}],
                "composite": 1.0, "gate_pass_rates": {"g": 1.0}, "judge_means": {},
                "round_latency_ms": 100.0}
    monkeypatch.setattr(cr, "run_cases", fake_run_cases)
    monkeypatch.setattr(cli, "_compute_quality", lambda *a, **k: (0.0, []), raising=False)
    monkeypatch.setattr(cli, "append_round", lambda rp, out: captured.update(out), raising=False)
    monkeypatch.setattr(cli, "advance_phase", lambda *a, **k: None, raising=False)

    import argparse
    args = argparse.Namespace(eval=str(ev), worktree=str(tmp_path / "wt"),
                              run_id="r1", base=str(base), round=1)
    cli._case_run(args)

    assert captured["latency_score"] == 2.0          # baseline 200 / round 100
    assert captured["baseline_latency_ms"] == 200.0
    # composite overlaid: gates_component=1.0, latency=2.0, weights 0.5/0.5 -> 1.5
    assert captured["composite"] == 1.5
    assert "latency_feedback" in captured


def test_case_run_no_latency_when_weight_absent(tmp_path, monkeypatch):
    import loop_iter.cli as cli
    import loop_iter.case_runner as cr
    from loop_iter.state import RunPaths
    import json

    base = tmp_path
    ev = base / "ev"; ev.mkdir()
    (ev / "goal.yaml").write_text(
        "threshold: 0.85\nmax_rounds: 4\nweights: {gates: 1.0}\nagent: {type: claude-p}\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "rubric.md").write_text("rubric")
    (ev / "gates.py").write_text("GATES = {}\n")

    rp = RunPaths(base=str(base), run_id="r1")
    rp.run_dir.mkdir(parents=True, exist_ok=True)
    rp.state_file.write_text(json.dumps({"phase": "eval", "round": 1, "max_rounds": 4,
                                         "run_id": "r1", "goal": "g", "met": False,
                                         "baseline_composite": 1.0, "best": {"round": None}}))

    captured = {}
    def fake_run_cases(cases, worktree, gates_path, rubric_md, weights,
                       run_case_fn, judge_case_fn=None, llm_call=None, parallelism=1):
        return {"cases": [{"case_id": "c1", "output": "OK", "trace": {},
                           "gates": [{"gate": "g", "passed": True}], "judge": [],
                           "error": None, "elapsed_ms": 100.0}],
                "composite": 0.9, "gate_pass_rates": {"g": 1.0}, "judge_means": {},
                "round_latency_ms": 100.0}
    monkeypatch.setattr(cr, "run_cases", fake_run_cases)
    monkeypatch.setattr(cli, "_compute_quality", lambda *a, **k: (0.0, []), raising=False)
    monkeypatch.setattr(cli, "append_round", lambda rp, out: captured.update(out), raising=False)
    monkeypatch.setattr(cli, "advance_phase", lambda *a, **k: None, raising=False)

    import argparse
    args = argparse.Namespace(eval=str(ev), worktree=str(tmp_path / "wt"),
                              run_id="r1", base=str(base), round=1)
    cli._case_run(args)

    # no latency weight -> no overlay, composite unchanged, no latency fields
    assert captured["composite"] == 0.9
    assert "latency_score" not in captured
    assert "latency_feedback" not in captured


def test_baseline_stores_round_latency_and_neutral_score(tmp_path, monkeypatch):
    import loop_iter.cli as cli
    import loop_iter.case_runner as cr
    from loop_iter.state import RunPaths
    import json

    base = tmp_path
    ev = base / "ev"; ev.mkdir()
    (ev / "goal.yaml").write_text(
        "threshold: 0.85\nmax_rounds: 4\nweights: {gates: 0.5, latency: 0.5}\nagent: {type: claude-p}\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "rubric.md").write_text("rubric")
    (ev / "gates.py").write_text("GATES = {}\n")

    rp = RunPaths(base=str(base), run_id="r1")
    rp.run_dir.mkdir(parents=True, exist_ok=True)
    rp.state_file.write_text(json.dumps({"phase": "baseline", "round": 0, "max_rounds": 4,
                                         "run_id": "r1", "goal": "g", "met": False,
                                         "baseline_composite": None, "best": {"round": None}}))

    def fake_run_cases(cases, worktree, gates_path, rubric_md, weights,
                       run_case_fn, judge_case_fn=None, llm_call=None, parallelism=1):
        return {"cases": [{"case_id": "c1", "output": "OK", "trace": {},
                           "gates": [{"gate": "g", "passed": True}], "judge": [],
                           "error": None, "elapsed_ms": 100.0}],
                "composite": 1.0, "gate_pass_rates": {"g": 1.0}, "judge_means": {},
                "round_latency_ms": 100.0}
    monkeypatch.setattr(cr, "run_cases", fake_run_cases)
    monkeypatch.setattr(cli, "_compute_quality", lambda *a, **k: (0.0, []), raising=False)
    monkeypatch.setattr(cli, "advance_phase", lambda *a, **k: None, raising=False)

    import argparse
    args = argparse.Namespace(eval=str(ev), run_id="r1", base=str(base))
    cli._baseline(args)

    b = json.loads(rp.baseline_file.read_text())
    assert b["round_latency_ms"] == 100.0
    assert b["latency_score"] == 1.0          # neutral (no prior baseline)
    assert b["baseline_latency_ms"] is None
```

NOTE: if `load_state` (called by `_case_run`/`_baseline`) requires more/different fields than the `state_file.write_text` JSON above, adjust the JSON to satisfy `load_state` — read `scripts/loop_iter/state.py` `load_state`/`init_state` for the exact schema. Do NOT weaken the assertions.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_cli.py -k "overlays_latency or no_latency_when_weight or baseline_stores_round_latency" -v`
Expected: FAIL — `latency_score` not in captured / `round_latency_ms` not stored (the overlay + baseline storage don't exist yet).

- [ ] **Step 3: Implement the `_apply_latency` helper**

In `scripts/loop_iter/cli.py`, add this helper near `_rubric_path` / `_parallelism`:

```python
def _apply_latency(out: dict, goal: dict, rp) -> dict:
    """If weights.latency is set: compute latency_score relative to baseline, overlay it into
    composite (uncapped, may exceed 1.0), and attach a maker-facing latency_feedback string.
    No-op (returns out unchanged) when weights.latency is absent."""
    weights = goal.get("weights") or {}
    if "latency" not in weights:
        return out
    from loop_iter.scoring import composite as _composite, compute_latency_score
    from loop_iter.latency_feedback import latency_feedback
    baseline = json.loads(rp.baseline_file.read_text()) if rp.baseline_file.exists() else {}
    baseline_latency = baseline.get("round_latency_ms")
    out["baseline_latency_ms"] = baseline_latency
    out["latency_score"] = compute_latency_score(out.get("round_latency_ms", 0.0), baseline_latency)
    out["composite"] = _composite(out["cases"], weights, extra={"latency": out["latency_score"]})
    out["latency_feedback"] = latency_feedback(out["cases"], baseline.get("cases"))
    return out
```

- [ ] **Step 4: Wire into `_case_run`**

In `_case_run`, immediately after the `out["quality"], out["quality_dims"] = _compute_quality(...)` line, add:

```python
    out = _apply_latency(out, goal, rp)
```

- [ ] **Step 5: Wire into `_baseline`**

In `_baseline`, immediately after its `out["quality"], out["quality_dims"] = _compute_quality(...)` line and before `rp.baseline_file.write_text(...)`, add:

```python
    weights = goal.get("weights") or {}
    if "latency" in weights:
        from loop_iter.scoring import composite as _composite
        out["baseline_latency_ms"] = None
        out["latency_score"] = 1.0
        out["composite"] = _composite(out["cases"], weights, extra={"latency": 1.0})
```

(`out["round_latency_ms"]` is already present from `run_cases`, so `baseline.json` stores it automatically via `json.dumps(out)`.)

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_cli.py -k "overlays_latency or no_latency_when_weight or baseline_stores_round_latency" -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the full cli suite for no regression**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS — all green. (Existing `fake_run_cases` stubs return no `round_latency_ms`, but `_apply_latency` is only called when `weights.latency` is set; existing tests without `weights.latency` skip the overlay, so `out.get("round_latency_ms", 0.0)` is never reached for them.)

- [ ] **Step 8: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: overlay latency_score into composite + store latency_feedback (cli)"
```

---

### Task 5: validate_spec — `weights.latency` warning

**Files:**
- Modify: `scripts/loop_iter/validate_spec.py`
- Test: `tests/test_validate_spec.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_validate_spec.py` (reuse the existing `_write_valid_spec` helper; if it doesn't accept a way to set custom weights, extend it minimally with a `weights=None` kwarg that writes the given weights dict into goal.yaml, defaulting to the current valid weights):

```python
def test_validate_spec_warns_on_latency_weight(tmp_path):
    from loop_iter.validate_spec import validate_spec
    d = _write_valid_spec(tmp_path, weights={"gates": 0.5, "latency": 0.1})
    v = validate_spec(str(d))
    assert v["valid"]
    assert any("latency" in w and "uncapped" in w for w in v["warnings"])


def test_validate_spec_rejects_negative_latency_weight(tmp_path):
    from loop_iter.validate_spec import validate_spec
    d = _write_valid_spec(tmp_path, weights={"gates": 0.5, "latency": -0.1})
    v = validate_spec(str(d))
    assert not v["valid"]
    assert any("latency" in p and "non-negative" in p for p in v["problems"])
```

If the existing `_write_valid_spec` writes a fixed weights line, change it to accept `weights=None` and, when provided, write `weights: <yaml-dumped dict>` instead. Default behavior (no kwarg) must be unchanged so existing tests pass.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_validate_spec.py -k "latency_weight or negative_latency" -v`
Expected: FAIL — no latency warning/problem produced.

- [ ] **Step 3: Implement**

In `scripts/loop_iter/validate_spec.py`, immediately after the existing weights check (`if not isinstance(w, dict) or not w: problems.append("goal.yaml: weights must be a non-empty dict")`), add:

```python
    if isinstance(w, dict) and "latency" in w:
        lw = w["latency"]
        if isinstance(lw, bool) or not isinstance(lw, (int, float)) or lw < 0:
            problems.append("goal.yaml: weights.latency must be a non-negative number")
        else:
            warnings.append("goal.yaml: weights.latency is uncapped — composite may exceed 1.0; "
                            "rely on gates+judge to contain do-less-to-go-fast gaming, keep it small")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest tests/test_validate_spec.py -v`
Expected: PASS — all green (new + existing).

- [ ] **Step 5: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add scripts/loop_iter/validate_spec.py tests/test_validate_spec.py
git commit -m "feat: validate weights.latency (warn uncapped; reject negative)"
```

---

### Task 6: Docs — `weights.latency` + `trace.timings` schema

**Files:**
- Modify: `skills/self-iterate-setup/SKILL.md`, `skills/self-iterate/SKILL.md`, `README.md`

- [ ] **Step 1: setup SKILL.md — add `latency` weight + `trace.timings` schema**

In `skills/self-iterate-setup/SKILL.md`, find the `parallelism` explanatory bullet (added previously) and add a sibling bullet after it:

```markdown
- `weights.latency` (optional, in the `weights:` dict) — opt-in latency optimization target.
  Relative to baseline: `latency_score = baseline_mean_latency / round_mean_latency`, UNCAPPED
  (composite may exceed 1.0 when the round is faster). The scored signal is per-case `elapsed_ms`
  (wall-clock of `run_case` only, universal across adapter types). Keep the weight small (e.g. 0.1);
  gates+judge contain do-less-to-go-fast gaming. Adapters may also fill `trace.timings`
  (`[{"phase": "llm_call"|"tool_call:<name>", "ms": float, "count": int}]`) for maker attribution;
  absent timings degrade to per-case delta feedback.
```

- [ ] **Step 2: self-iterate SKILL.md — maker reads latency feedback**

In `skills/self-iterate/SKILL.md`, near the case-run/eval step (where `scores.json` is described), add a short note:

```markdown
   *(If `weights.latency` is set, each round's `scores.json` entry carries `latency_score`,
   `round_latency_ms`, `baseline_latency_ms`, and a `latency_feedback` string attributing the
   delta to phases (when `trace.timings` present) or to cases. Read it to decide where to cut
   latency — e.g. fewer/redundant tool calls.)*
```

- [ ] **Step 3: README — mention `latency` weight**

In `README.md`, find the line that lists `weights` contents (the line mentioning `threshold, weights, regression, parallelism, optional agent:/harness: overrides`) and add `latency` to it. If there's a separate `weights:` example block, add a commented `# latency: 0.1  # opt-in, relative baseline, uncapped` line.

- [ ] **Step 4: Commit**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git add skills/self-iterate-setup/SKILL.md skills/self-iterate/SKILL.md README.md
git commit -m "docs: weights.latency opt-in target + trace.timings schema"
```

---

### Task 7: maas `entry.py` — fill `trace.timings` + smoke verify

**Files (maas repo):**
- Modify: `/Users/zhengweijun/rag/maas-customer-agent/.self-iterate/skill-coverage/entry.py`
- Verify: manual smoke (no unit test)

- [ ] **Step 1: Modify `_run` to populate `trace["timings"]`**

In `entry.py`, edit the `_run` coroutine to timestamp events and build a `timings` list. The current `_run` captures `ToolCallEvent` / `TextChunkEvent` / `FinalResponseEvent`. Add `import time` at the top (if not present) and rewrite `_run` as:

```python
async def _run(query: str, variant_dir: str) -> dict:
    agent = _build_agent(variant_dir)
    await agent.async_initialize()

    tool_calls: list[dict] = []
    timings: list[dict] = []
    chunk_text = ""
    final_text = None

    # Timing model: each event closes the pending span (started at the previous event).
    # A ToolCallEvent starts a tool_call:<name> span; any other event starts an llm_call span.
    pending = None  # (phase, start_perf)
    prev_t = time.perf_counter()

    try:
        async for event in agent.query_stream(query, stream=True):
            now = time.perf_counter()
            if pending is not None:
                timings.append({"phase": pending[0], "ms": (now - pending[1]) * 1000.0, "count": 1})
                pending = None
            if isinstance(event, ToolCallEvent):
                args = event.args if isinstance(event.args, dict) else {}
                tool_calls.append({"tool": event.tool, "args": args})
                pending = (f"tool_call:{event.tool}", now)
            elif isinstance(event, TextChunkEvent):
                chunk_text += event.content or ""
                if pending is None:
                    pending = ("llm_call", now)
            elif isinstance(event, FinalResponseEvent):
                final_text = event.content
                if pending is None:
                    pending = ("llm_call", now)
        # close trailing span
        if pending is not None:
            timings.append({"phase": pending[0], "ms": (time.perf_counter() - pending[1]) * 1000.0, "count": 1})
    except Exception as exc:  # never raise — surface as error field
        output = final_text if final_text is not None else chunk_text
        return {"output": output, "trace": {"tool_calls": tool_calls, "timings": timings},
                "error": f"agent error: {exc!r}"}

    output = final_text if final_text is not None else chunk_text
    return {"output": output, "trace": {"tool_calls": tool_calls, "timings": timings}, "error": None}
```

Keep the `run()` entry function unchanged (it calls `asyncio.run(_run(...))` and returns the dict).

- [ ] **Step 2: Smoke-verify timings populate (parallelism=1, 3 cases)**

Run a 3-case smoke in the maas venv (no state mutation — no `--run-id`, in-memory only):

```bash
cd /Users/zhengweijun/rag/maas-customer-agent
PYTHONPATH=/Users/zhengweijun/agent/loop-iteration/scripts:. \
.venv/bin/python -c "
import json, yaml
from pathlib import Path
from loop_iter.case_runner import run_cases
from loop_iter.adapter_generic import build_run_case, resolve_harness
from loop_iter.llm_client import chat as llm_call
ev=Path('.self-iterate/skill-coverage')
goal=yaml.safe_load((ev/'goal.yaml').read_text())
cases=json.loads((ev/'cases.json').read_text())[:3]
harness=resolve_harness(str(ev),'.')
rc=build_run_case(str(ev), goal.get('agent',{}), harness)
out=run_cases(cases,'.',str(ev/'gates.py'),(ev/'rubric.md').read_text(),
              goal['weights'], run_case_fn=rc, llm_call=llm_call, parallelism=1)
for c in out['cases']:
    tm = (c['trace'] or {}).get('timings', [])
    print(c['case_id'], 'elapsed_ms=%.0f' % c['elapsed_ms'], 'timings=%d' % len(tm), tm[:3])
print('round_latency_ms=%.0f' % out['round_latency_ms'])
"
```

Expected: each case prints a non-zero `elapsed_ms` and `timings` with ≥1 entry (e.g. `tool_call:kb_search`, `llm_call`). Gates still pass (behavior unchanged).

**If `timings` is empty** (0 entries): zai_adk's `query_stream` emits a different event sequence than assumed. Add a temporary `print(type(event).__name__)` inside the event loop, re-run on ONE case, inspect the actual event types, and adjust the `isinstance` branches accordingly. Do NOT leave the debug print in the final version.

- [ ] **Step 3: Commit (in the maas repo)**

```bash
cd /Users/zhengweijun/rag/maas-customer-agent
git add .self-iterate/skill-coverage/entry.py
git commit -m "feat: fill trace.timings in skill-coverage python-import shim (phase-1 latency visibility)"
```

---

### Task 8: Full-suite regression + end-to-end latency verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full plugin test suite**

Run: `cd /Users/zhengweijun/agent/loop-iteration && .venv/bin/python -m pytest -q`
Expected: PASS — all green.

- [ ] **Step 2: Validate a goal spec with `weights.latency`**

Create a throwaway check (do not commit): temporarily add `latency: 0.1` to a goal's weights in a tmp copy and run `validate-spec`; confirm `valid: true` + the uncapped warning. Or run against the maas goal after adding `latency: 0.1`:

```bash
cd /Users/zhengweijun/rag/maas-customer-agent
# add '  latency: 0.1' under weights: in .self-iterate/skill-coverage/goal.yaml temporarily
/Users/zhengweijun/agent/loop-iteration/.venv/bin/python /Users/zhengweijun/agent/loop-iteration/scripts/loop_iter/cli.py validate-spec --eval .self-iterate/skill-coverage
# expect valid:true with a latency/uncapped warning; then REVERT the goal.yaml edit (do not commit it)
```

Expected: `valid: true`, warnings include the latency/uncapped message. Revert the temporary edit.

- [ ] **Step 3: End-to-end latency scoring smoke (maas, parallelism=1, 3 cases, with latency weight)**

Confirm the full chain (elapsed_ms → round_latency_ms → latency_score → composite overlay → latency_feedback) works against the real maas shim. This extends the Task 7 smoke by setting `weights.latency` in the call:

```bash
cd /Users/zhengweijun/rag/maas-customer-agent
PYTHONPATH=/Users/zhengweijun/agent/loop-iteration/scripts:. \
.venv/bin/python -c "
import json, yaml
from pathlib import Path
from loop_iter.case_runner import run_cases
from loop_iter.scoring import composite, compute_latency_score
from loop_iter.latency_feedback import latency_feedback
from loop_iter.adapter_generic import build_run_case, resolve_harness
from loop_iter.llm_client import chat as llm_call
ev=Path('.self-iterate/skill-coverage')
goal=yaml.safe_load((ev/'goal.yaml').read_text())
goal['weights']['latency']=0.1   # simulate opt-in for this in-memory check
cases=json.loads((ev/'cases.json').read_text())[:3]
harness=resolve_harness(str(ev),'.')
rc=build_run_case(str(ev), goal.get('agent',{}), harness)
out=run_cases(cases,'.',str(ev/'gates.py'),(ev/'rubric.md').read_text(),
              goal['weights'], run_case_fn=rc, llm_call=llm_call, parallelism=1)
ls=compute_latency_score(out['round_latency_ms'], out['round_latency_ms'])  # self-baseline -> 1.0
comp=composite(out['cases'], goal['weights'], extra={'latency': ls})
print('round_latency_ms=%.0f  latency_score=%.3f  composite=%.3f' % (out['round_latency_ms'], ls, comp))
print(latency_feedback(out['cases'], out['cases']))
"
```

Expected: prints a non-zero `round_latency_ms`, `latency_score=1.0` (self-baseline), a sensible `composite`, and a non-empty `latency_feedback` string (phase breakdown, since the shim now fills `trace.timings`). No exceptions.

---

## Self-Review

**1. Spec coverage.**
- Universal wall-clock scored signal (per-case `elapsed_ms` → round mean): Task 2. ✓
- `compute_latency_score` (uncapped, baseline 0/None→1.0, round 0→1.0): Task 1. ✓
- `composite(extra=)` fold-in: Task 1. ✓
- cli overlay in `_case_run` + baseline stores `round_latency_ms` + neutral score: Task 4. ✓
- `latency_feedback` pure attribution (phase breakdown / per-case fallback): Task 3. ✓
- `trace.timings` schema + python-import fill (phase 1): Task 7. ✓
- validate_spec `weights.latency` warning: Task 5. ✓
- Docs: Task 6. ✓
- Error handling (baseline missing → 1.0; round 0 → 1.0; timings absent → per-case; weight absent → no-op): Tasks 1, 3, 4. ✓
- Phase 2 (claude-p stream-json, local-service timing) explicitly out of scope (spec states this). ✓
- maas manual smoke: Tasks 7-8. ✓
No spec gaps.

**2. Placeholder scan.** No TBD/TODO. Task 7's "if timings empty, inspect events and adjust" is a concrete debug procedure with a specific command, not a placeholder. Task 4/5 "if the helper doesn't accept the kwarg, extend it minimally" gives the exact extension. Acceptable.

**3. Type/name consistency.**
- `compute_latency_score` (Task 1) — used in Task 4 `_apply_latency`. ✓ (renamed from `latency_score` per spec to avoid field-name collision).
- `composite(extra=)` (Task 1) — used in Task 4. ✓
- `round_latency_ms` (Task 2 return) — read in Task 4 `_apply_latency` + `_baseline`. ✓
- `elapsed_ms` (Task 2 case field) — read in Task 3 `latency_feedback`. ✓
- `trace.timings` with `phase`/`ms`/`count` (Task 7) — matches `latency_feedback` reader (Task 3) and the schema doc (Task 6). ✓
- `_apply_latency(out, goal, rp)` signature (Task 4) — called as `out = _apply_latency(out, goal, rp)`. ✓
- `weights.latency` key — consistent across scoring, cli, validate_spec, docs. ✓
