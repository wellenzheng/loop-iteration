# Self-Iteration Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude-Code-native loop that self-iterates any agent's harness (prompt/skills/tools) until a user-defined, verifiable goal is met — proven end-to-end on a toy agent.

**Architecture:** A `self-iterate` skill defines one round (maker rewrites → checker evaluates → write state); `ralph`/`autopilot` (run-until-done) repeats it until the `goal-checker` (separate reviewer) confirms a verifiable stop condition. All generalization lives behind three seams — **adapter** (per agent: `apply_variant`/`run_case`), **eval spec** (per goal: gates + LLM-judge), **variant** (per round: harness files in a git worktree). The deterministic machinery (scoring, gates, judge, case-running, state, goal-check) is small Python, TDD'd; the maker/checker/rewriter are Claude sub-agents.

**Tech Stack:** Python 3.11+, pytest, PyYAML, httpx (LLM-judge), git worktrees, the `claude` CLI, Claude Code skills/sub-agents, OMC `ralph`/`autopilot` for run-until-done.

**Spec:** [docs/superpowers/specs/2026-06-23-self-iteration-loop-design.md](../specs/2026-06-23-self-iteration-loop-design.md)

---

## File Structure

```
loop-iteration/
├── pyproject.toml                         # NEW — deps + pytest config
├── src/loop_iter/                         # NEW — the small deterministic core
│   ├── __init__.py
│   ├── scoring.py                         # composite() + goal_met() — PURE
│   ├── gates.py                           # load_gates() + run_gates() — PURE-ish (imports user module)
│   ├── judge.py                           # judge_case() w/ strict output + gates-only fallback
│   ├── adapter.py                         # apply_variant() git-worktree overlay + remove_worktree()
│   ├── case_runner.py                     # run_cases() orchestrator + CLI (python -m loop_iter.case_runner)
│   ├── goal_check.py                      # CLI (python -m loop_iter.goal_check)
│   └── state.py                           # RunPaths + read/write progress.md, scores.json, snapshot
├── adapters/toy/                          # NEW — adapter #1 (ships in minimal version)
│   ├── run_case.py                        # real toy run_case (claude -p in the worktree)
│   ├── apply_variant.py                   # thin wrapper over loop_iter.adapter for toy paths
│   └── agent_files/                       # the toy agent's baseline harness
│       ├── SKILL.md
│       ├── prompt.md
│       └── tools.json
├── evals/toy-basic/                       # NEW — the toy goal's eval spec
│   ├── goal.yaml
│   ├── cases.json
│   ├── gates.py
│   └── judge.md
├── .claude/skills/
│   ├── loop-engineering/                  # exists
│   ├── self-iterate/                      # NEW — one round
│   │   └── SKILL.md
│   └── case-evaluator/                    # NEW — checker wrapper
│       └── SKILL.md
├── .claude/agents/                        # NEW — sub-agent definitions
│   ├── harness-rewriter.md                # maker
│   └── goal-checker.md                    # run-until-done reviewer
├── tests/                                 # NEW
│   ├── test_scoring.py
│   ├── test_gates.py
│   ├── test_judge.py
│   ├── test_adapter.py
│   ├── test_run_case.py
│   ├── test_state.py
│   ├── test_case_runner.py
│   ├── test_goal_check.py
│   └── test_golden_round.py               # integration: machinery loop w/ stubs
└── docs/superpowers/plans/2026-06-23-self-iteration-loop.md   # this file
```

**Data shapes (used across tasks — keep names exact):**

```python
Case        = {"id": str, "query": str, "expected": str|None}
Result      = {"case_id": str, "output": str, "trace": dict, "error": str|None}
GatePass    = {"gate": str, "passed": bool}
JudgeScore  = {"dim": str, "score": float}            # score 0-10
CaseScore   = {"case_id": str, "gates": [GatePass], "judge": [JudgeScore], "error": str|None}
RunScores   = {"round": int, "cases": [CaseScore], "composite": float,
               "gate_pass_rates": {str: float}, "judge_means": {str: float}}
Goal        = {"threshold": float, "max_rounds": int,
               "weights": {"gates": float, <dim>: float}, "regression": "block"|"allow"}
GoalVerdict = {"met": bool, "round": int, "composite": float,
               "gate_pass_rates": {str: float}, "regressed_gates": [str], "reason": str}
```

**Composite & stop-condition model (from spec §4.1):** `gate_pass_rates[g]` = fraction of cases gate *g* passed. `composite` (0-1) = `(w_gates·mean(gate_pass_rates) + Σ_dim w_dim·(judge_mean[dim]/10)) / (w_gates + Σ w_dim)`. Goal met = `composite ≥ threshold` AND `(regression=="allow" OR no gate regressed vs best)` AND `round ≤ max_rounds`.

---

## Task 1: Project scaffold + first green test

**Files:**
- Create: `pyproject.toml`
- Create: `src/loop_iter/__init__.py`
- Create: `tests/test_smoke.py`
- Modify: `.gitignore` (add venv/cache)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "loop-iter"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pyyaml>=6.0", "httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find] = { where = ["src"] }

[tool.pytest.ini_options]
pythonpath = ["src", "."]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `src/loop_iter/__init__.py`**

```python
"""loop-iter: a Claude-Code-native agent-harness self-iteration loop."""
__version__ = "0.1.0"
```

- [ ] **Step 3: Write the failing test `tests/test_smoke.py`**

```python
import loop_iter


def test_package_imports():
    assert loop_iter.__version__ == "0.1.0"
```

- [ ] **Step 4: Add venv/cache to `.gitignore`**

Append to `.gitignore`:
```
# --- python ---
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 5: Create venv, install, run test — verify it passes**

```bash
cd loop-iteration  # repo root
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/loop_iter/__init__.py tests/test_smoke.py .gitignore
git commit -m "feat: scaffold loop-iter python package with pytest"
```

---

## Task 2: Scoring — composite + goal_met (pure functions)

**Files:**
- Create: `src/loop_iter/scoring.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write the failing tests `tests/test_scoring.py`**

```python
from loop_iter.scoring import gate_pass_rates, judge_means, composite, regressed_gates, goal_met


def _cs(gates, judge):
    return {"case_id": "x", "gates": gates, "judge": judge, "error": None}


def test_gate_pass_rates_all_pass():
    cases = [_cs([{"gate": "exact", "passed": True}], [])] * 3
    assert gate_pass_rates(cases) == {"exact": 1.0}


def test_gate_pass_rates_partial():
    cases = [
        _cs([{"gate": "exact", "passed": True}], []),
        _cs([{"gate": "exact", "passed": False}], []),
    ]
    assert gate_pass_rates(cases) == {"exact": 0.5}


def test_judge_means():
    cases = [
        _cs([], [{"dim": "tone", "score": 8.0}]),
        _cs([], [{"dim": "tone", "score": 6.0}]),
    ]
    assert judge_means(cases) == {"tone": 7.0}


def test_composite_weights_gates_and_judge():
    # gates all pass (1.0), tone mean 10.0 -> /10 = 1.0; weights gates=1, tone=1 -> (1+1)/2 = 1.0
    cases = [_cs([{"gate": "exact", "passed": True}], [{"dim": "tone", "score": 10.0}])]
    assert composite(cases, {"gates": 1.0, "tone": 1.0}) == 1.0


def test_composite_mixed():
    cases = [_cs([{"gate": "exact", "passed": False}], [{"dim": "tone", "score": 5.0}])]
    # gates 0.0, tone 0.5 -> (1*0 + 1*0.5)/2 = 0.25
    assert composite(cases, {"gates": 1.0, "tone": 1.0}) == 0.25


def test_regressed_gates_detects_drop():
    assert regressed_gates({"a": 0.5, "b": 1.0}, {"a": 1.0, "b": 0.5}) == ["a"]


def test_goal_met_when_above_threshold_no_regression():
    cases = [_cs([{"gate": "exact", "passed": True}], [{"dim": "tone", "score": 10.0}])]
    v = goal_met(round_idx=1, case_scores=cases, weights={"gates": 1.0, "tone": 1.0},
                 threshold=0.8, max_rounds=3, best_gate_rates={"exact": 1.0})
    assert v["met"] is True
    assert v["composite"] == 1.0
    assert v["regressed_gates"] == []


def test_goal_not_met_when_gate_regressed_and_policy_block():
    cases = [_cs([{"gate": "exact", "passed": False}], [{"dim": "tone", "score": 10.0}])]
    v = goal_met(round_idx=1, case_scores=cases, weights={"gates": 1.0, "tone": 1.0},
                 threshold=0.5, max_rounds=3, best_gate_rates={"exact": 1.0},
                 regression_policy="block")
    # composite = (1*0 + 1*1)/2 = 0.5 >= 0.5, but exact regressed 1.0->0.0 -> blocked
    assert v["met"] is False
    assert v["regressed_gates"] == ["exact"]


def test_goal_not_met_when_over_max_rounds():
    cases = [_cs([{"gate": "exact", "passed": True}], [{"dim": "tone", "score": 10.0}])]
    v = goal_met(round_idx=4, case_scores=cases, weights={"gates": 1.0, "tone": 1.0},
                 threshold=0.8, max_rounds=3, best_gate_rates={"exact": 1.0})
    assert v["met"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.scoring'`

- [ ] **Step 3: Write `src/loop_iter/scoring.py`**

```python
from __future__ import annotations

def gate_pass_rates(case_scores: list[dict]) -> dict[str, float]:
    """Fraction of cases each gate passed (0-1)."""
    names: list[str] = []
    seen: set[str] = set()
    for c in case_scores:
        for g in c.get("gates", []):
            if g["gate"] not in seen:
                seen.add(g["gate"]); names.append(g["gate"])
    rates: dict[str, float] = {}
    for name in names:
        rows = [g for c in case_scores for g in c.get("gates", []) if g["gate"] == name]
        rates[name] = sum(1 for g in rows if g["passed"]) / len(rows) if rows else 0.0
    return rates


def judge_means(case_scores: list[dict]) -> dict[str, float]:
    """Mean score per judge dim across cases (0-10)."""
    names: list[str] = []
    seen: set[str] = set()
    for c in case_scores:
        for d in c.get("judge", []):
            if d["dim"] not in seen:
                seen.add(d["dim"]); names.append(d["dim"])
    means: dict[str, float] = {}
    for name in names:
        vals = [d["score"] for c in case_scores for d in c.get("judge", []) if d["dim"] == name]
        means[name] = sum(vals) / len(vals) if vals else 0.0
    return means


def composite(case_scores: list[dict], weights: dict[str, float]) -> float:
    """Weighted composite in 0-1. weights has key 'gates' + judge dim names."""
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
    return acc / w_total if w_total else 0.0


def regressed_gates(current: dict[str, float], best: dict[str, float]) -> list[str]:
    return [g for g, r in current.items() if g in best and r < best[g]]


def goal_met(round_idx: int, case_scores: list[dict], weights: dict[str, float],
             threshold: float, max_rounds: int, best_gate_rates: dict[str, float] | None,
             regression_policy: str = "block") -> dict:
    gpr = gate_pass_rates(case_scores)
    comp = composite(case_scores, weights)
    best = best_gate_rates or {}
    regressed = regressed_gates(gpr, best)
    blocked = regression_policy == "block" and bool(regressed)
    within = round_idx <= max_rounds
    met = (comp >= threshold) and (not blocked) and within
    if not within:
        reason = f"hit max_rounds ({max_rounds})"
    elif blocked:
        reason = f"gate regression: {regressed}"
    elif comp < threshold:
        reason = f"composite {comp:.3f} < threshold {threshold}"
    else:
        reason = "met"
    return {"met": met, "round": round_idx, "composite": comp,
            "gate_pass_rates": gpr, "regressed_gates": regressed, "reason": reason}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scoring.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/loop_iter/scoring.py tests/test_scoring.py
git commit -m "feat: add composite scoring and goal_met stop-condition logic"
```

---

## Task 3: Gates loader + runner

**Files:**
- Create: `src/loop_iter/gates.py`
- Test: `tests/test_gates.py`
- Test fixture: `tests/_gates_fixture.py`

- [ ] **Step 1: Write the failing tests `tests/test_gates.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gates.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.gates'`

- [ ] **Step 3: Write `src/loop_iter/gates.py`**

```python
from __future__ import annotations
import importlib.util
from pathlib import Path

def load_gates(gates_path: str) -> dict[str, callable]:
    """Load a user gates module defining GATES = {name: fn(result, case) -> {passed: bool}}."""
    p = Path(gates_path).resolve()
    spec = importlib.util.spec_from_file_location(f"_gates_{p.stem}_{p.stat().st_mtime_ns}", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    if not hasattr(mod, "GATES") or not isinstance(mod.GATES, dict):
        raise ValueError(f"{gates_path} must define GATES = {{name: fn}}")
    return dict(mod.GATES)


def run_gates(result: dict, case: dict, gates: dict[str, callable]) -> list[dict]:
    """Run every gate; a gate that raises counts as failed (never crashes the round)."""
    out: list[dict] = []
    for name, fn in gates.items():
        try:
            verdict = fn(result, case)
            passed = bool(verdict.get("passed", False))
        except Exception:
            passed = False
        out.append({"gate": name, "passed": passed})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gates.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/loop_iter/gates.py tests/test_gates.py
git commit -m "feat: add gates loader and fault-tolerant gate runner"
```

---

## Task 4: LLM-judge with strict output + gates-only fallback

**Files:**
- Create: `src/loop_iter/judge.py`
- Test: `tests/test_judge.py`

- [ ] **Step 1: Write the failing tests `tests/test_judge.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_judge.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.judge'`

- [ ] **Step 3: Write `src/loop_iter/judge.py`**

```python
from __future__ import annotations
import json

def _parse_dims(text: str) -> list[dict] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    dims = data.get("dims") if isinstance(data, dict) else None
    if not isinstance(dims, list):
        return None
    clean = []
    for d in dims:
        if isinstance(d, dict) and "dim" in d and "score" in d:
            try:
                clean.append({"dim": str(d["dim"]), "score": float(d["score"])})
            except (TypeError, ValueError):
                return None
    return clean or None

def judge_case(result: dict, case: dict, judge_md: str, llm_call,
               model: str = "glm-4.7") -> list[dict] | None:
    """Ask the LLM to score the case per the rubric. Returns [{dim, score}] or None.

    None is the gates-only fallback signal (no hand-rolled JSON repair — strict output,
    one retry, then degrade). llm_call(prompt, model) -> str.
    """
    prompt = (
        f"{judge_md}\n\n"
        f"Return ONLY strict JSON: {{\"dims\": [{{\"dim\": <name>, \"score\": <0-10>}}]}}.\n"
        f"Case query: {case.get('query')}\n"
        f"Expected: {case.get('expected')}\n"
        f"Agent output: {result.get('output')}\n"
    )
    for _ in range(2):  # initial + one retry
        dims = _parse_dims(llm_call(prompt, model))
        if dims is not None:
            return dims
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_judge.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/loop_iter/judge.py tests/test_judge.py
git commit -m "feat: add LLM judge with strict output and gates-only fallback"
```

---

## Task 5: apply_variant — hermetic git-worktree overlay

**Files:**
- Create: `src/loop_iter/adapter.py`
- Test: `tests/test_adapter.py`

- [ ] **Step 1: Write the failing tests `tests/test_adapter.py`**

```python
import subprocess, textwrap
from pathlib import Path
from loop_iter.adapter import apply_variant, remove_worktree, snapshot_variant


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent_files").mkdir()
    (repo / "agent_files" / "SKILL.md").write_text("baseline")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}, check=True)
    return repo


def test_apply_variant_creates_worktree_and_source_untouched(tmp_path):
    repo = _repo(tmp_path)
    wt = apply_variant(repo_root=str(repo), baseline_ref="HEAD", agent_subdir="agent_files")
    assert Path(wt, "agent_files", "SKILL.md").read_text() == "baseline"
    # editing the worktree must NOT touch the source repo
    Path(wt, "agent_files", "SKILL.md").write_text("edited")
    assert (repo / "agent_files" / "SKILL.md").read_text() == "baseline"
    remove_worktree(wt)


def test_snapshot_variant_copies_subdir(tmp_path):
    repo = _repo(tmp_path)
    wt = apply_variant(str(repo), "HEAD", "agent_files")
    Path(wt, "agent_files", "SKILL.md").write_text("round1")
    dest = tmp_path / "snap"
    snapshot_variant(wt, "agent_files", str(dest))
    assert (dest / "SKILL.md").read_text() == "round1"
    remove_worktree(wt)


def test_remove_worktree_cleans_up(tmp_path):
    repo = _repo(tmp_path)
    wt = apply_variant(str(repo), "HEAD", "agent_files")
    remove_worktree(wt)
    assert not Path(wt).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.adapter'`

- [ ] **Step 3: Write `src/loop_iter/adapter.py`**

```python
from __future__ import annotations
import shutil
import subprocess
import tempfile
from pathlib import Path

def _git(repo: str, *args: str) -> str:
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {args} failed: {out.stderr.strip()}")
    return out.stdout.strip()

def apply_variant(repo_root: str, baseline_ref: str, agent_subdir: str) -> str:
    """Create a detached worktree of repo_root at baseline_ref. The maker edits
    <worktree>/<agent_subdir> there; the source repo is never mutated mid-loop.
    Returns the worktree path."""
    wt = tempfile.mkdtemp(prefix="loopiter_wt_")
    # mkdtemp created the dir; worktree add needs a non-existent path
    shutil.rmtree(wt)
    _git(repo_root, "worktree", "add", "--detach", wt, baseline_ref)
    return wt

def snapshot_variant(worktree: str, agent_subdir: str, dest: str) -> None:
    """Copy the variant's harness subdir to dest (per-round snapshot)."""
    src = Path(worktree, agent_subdir)
    shutil.copytree(src, dest, dirs_exist_ok=True)

def remove_worktree(worktree: str) -> None:
    """Tear down a worktree; never raises (crash-safe cleanup)."""
    try:
        _git(worktree, "worktree", "remove", "--force", worktree)
    except Exception:
        pass
    p = Path(worktree)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_adapter.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/loop_iter/adapter.py tests/test_adapter.py
git commit -m "feat: add hermetic git-worktree variant isolation (apply/snapshot/remove)"
```

---

## Task 6: Toy adapter `run_case` (invokes the agent under test)

**Files:**
- Create: `adapters/toy/run_case.py`
- Test: `tests/test_run_case.py`

> The real toy `run_case` shells out to `claude -p` in the worktree. To keep the test deterministic, we test the *contract* with a fake agent script (no real Claude). A live `claude` run is verified manually in Task 16.

- [ ] **Step 1: Write the failing tests `tests/test_run_case.py`**

```python
import subprocess, textwrap
from pathlib import Path
import importlib.util

def _load_run_case():
    # load adapters/toy/run_case.py as a module without package context
    p = Path("adapters/toy/run_case.py").resolve()
    spec = importlib.util.spec_from_file_location("toy_run_case", p)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _repo_with_agent(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "agent_files").mkdir()
    (repo / "agent_files" / "SKILL.md").write_text("answer in one word")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}, check=True)
    return repo


def test_run_case_returns_result_shape_with_fake_agent(tmp_path, monkeypatch):
    from loop_iter.adapter import apply_variant, remove_worktree
    repo = _repo_with_agent(tmp_path)
    wt = apply_variant(str(repo), "HEAD", "agent_files")
    mod = _load_run_case()

    # fake agent: echo the query uppercased
    fake_agent = tmp_path / "fake_agent.sh"
    fake_agent.write_text("#!/bin/sh\necho \"$(cat)\" | tr a-z A-Z\n")
    fake_agent.chmod(0o755)
    monkeypatch.setattr(mod, "AGENT_CMD", [str(fake_agent)])

    result = mod.run_case(
        case={"id": "c1", "query": "hello", "expected": None},
        worktree=wt, agent_subdir="agent_files",
    )
    assert result["case_id"] == "c1"
    assert result["output"].strip() == "HELLO"
    assert result["error"] is None
    remove_worktree(wt)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run_case.py -q`
Expected: FAIL — file `adapters/toy/run_case.py` not found / `AttributeError`.

- [ ] **Step 3: Write `adapters/toy/run_case.py`**

```python
"""Toy adapter: run one case against the agent under test in a worktree.

For the toy agent the "agent" is a Claude Code session reading the variant's
agent_files/ (its SKILL.md/prompt). In production this calls the `claude` CLI;
AGENT_CMD is overridable so tests can inject a fake agent (no real Claude).
"""
from __future__ import annotations
import subprocess

# Default: real Claude Code, headless, running in the worktree so variant skills load.
AGENT_CMD = ["claude", "-p", "--permission-mode", "bypassPermissions"]

def run_case(case: dict, worktree: str, agent_subdir: str, timeout: int = 120) -> dict:
    """Run the agent on one case; return a Result. A crash/timeout scores 0, never raises."""
    try:
        prompt = case.get("query", "")
        proc = subprocess.run(
            AGENT_CMD, cwd=worktree, input=prompt,
            capture_output=True, text=True, timeout=timeout,
        )
        output = proc.stdout.strip()
        error = None if proc.returncode == 0 else f"exit {proc.returncode}: {proc.stderr.strip()[:300]}"
    except Exception as exc:  # timeout, missing binary, etc.
        output, error = "", f"run_case error: {exc!r}"
    return {"case_id": case["id"], "output": output, "trace": {}, "error": error}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_case.py -q`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add adapters/toy/run_case.py tests/test_run_case.py
git commit -m "feat: add toy adapter run_case (claude-backed, fake-agent testable)"
```

---

## Task 7: State read/write (the spine)

**Files:**
- Create: `src/loop_iter/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests `tests/test_state.py`**

```python
import json
from loop_iter.state import RunPaths, write_scores, load_scores, write_progress, append_round

def test_run_paths_layout(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="20260623_120000_abcd1234")
    assert rp.progress.name == "progress.md"
    assert rp.scores.name == "scores.json"
    assert rp.scores.parent.name == "20260623_120000_abcd1234"

def test_write_and_load_scores_roundtrip(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    scores = {"round": 1, "cases": [], "composite": 0.5,
              "gate_pass_rates": {}, "judge_means": {}}
    write_scores(rp, scores)
    assert load_scores(rp) == scores

def test_append_round_accumulates(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    append_round(rp, {"round": 1, "composite": 0.4, "gate_pass_rates": {"exact": 1.0}, "cases": [], "judge_means": {}})
    append_round(rp, {"round": 2, "composite": 0.8, "gate_pass_rates": {"exact": 1.0}, "cases": [], "judge_means": {}})
    data = load_scores(rp)
    assert data["rounds"][0]["composite"] == 0.4
    assert data["rounds"][1]["composite"] == 0.8
    assert data["best_round"] == 2

def test_write_progress_creates_file(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    write_progress(rp, "## Round 1\ncomposite 0.4")
    assert "Round 1" in rp.progress.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.state'`

- [ ] **Step 3: Write `src/loop_iter/state.py`**

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass
class RunPaths:
    base: str
    run_id: str

    @property
    def run_dir(self) -> Path:
        return Path(self.base, ".loop", "iterate", self.run_id)

    @property
    def scores(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir / "scores.json"

    @property
    def progress(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir / "progress.md"

    @property
    def variants_dir(self) -> Path:
        d = self.run_dir / "variants"; d.mkdir(parents=True, exist_ok=True)
        return d

def _load_raw(rp: RunPaths) -> dict:
    if not rp.scores.exists():
        return {"run_id": rp.run_id, "rounds": [], "best_round": None}
    return json.loads(rp.scores.read_text())

def write_scores(rp: RunPaths, data: dict) -> None:
    rp.scores.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def load_scores(rp: RunPaths) -> dict:
    return _load_raw(rp)

def append_round(rp: RunPaths, run_scores: dict) -> dict:
    data = _load_raw(rp)
    data["rounds"].append(run_scores)
    data["best_round"] = max(data["rounds"], key=lambda r: r["composite"])["round"]
    write_scores(rp, data)
    return data

def write_progress(rp: RunPaths, body: str) -> None:
    rp.progress.write_text(f"# Run {rp.run_id}\n\n{body}\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/loop_iter/state.py tests/test_state.py
git commit -m "feat: add on-disk run state (scores, progress, best-round tracking)"
```

---

## Task 8: case_runner — orchestrate run_cases + gates + judge + composite

**Files:**
- Create: `src/loop_iter/case_runner.py`
- Test: `tests/test_case_runner.py`

- [ ] **Step 1: Write the failing tests `tests/test_case_runner.py`**

```python
from loop_iter.case_runner import run_cases

def _stub_run_case(output_map):
    """Returns a run_case that emits a fixed output per case id."""
    def rc(case, worktree, agent_subdir):
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

def test_run_cases_computes_composite(tmp_path, monkeypatch):
    cases = [{"id": "c1", "query": "q", "expected": None},
             {"id": "c2", "query": "q", "expected": None}]
    rc = _stub_run_case({"c1": "OK", "c2": "nope"})
    # judge returns full marks always
    judge = lambda result, case, judge_md, llm_call: [{"dim": "tone", "score": 10.0}]
    out = run_cases(
        cases=cases, worktree="/tmp/ignored", agent_subdir="agent_files",
        gates_path=_gate_mod(tmp_path), judge_md="x",
        weights={"gates": 1.0, "tone": 1.0},
        run_case_fn=rc, judge_case_fn=judge, llm_call=None,
    )
    # gate pass-rate has_ok = 1/2 = 0.5; tone mean 10 -> 1.0 -> (1*0.5 + 1*1)/2 = 0.75
    assert out["composite"] == 0.75
    assert out["gate_pass_rates"] == {"has_ok": 0.5}
    assert out["judge_means"] == {"tone": 10.0}
    assert len(out["cases"]) == 2

def test_run_cases_falls_back_to_gates_only_when_judge_none(tmp_path):
    cases = [{"id": "c1", "query": "q", "expected": None}]
    rc = _stub_run_case({"c1": "OK"})
    judge = lambda *a, **k: None   # judge failed -> gates-only
    out = run_cases(
        cases=cases, worktree="/tmp/x", agent_subdir="agent_files",
        gates_path=_gate_mod(tmp_path), judge_md="x",
        weights={"gates": 1.0, "tone": 1.0},
        run_case_fn=rc, judge_case_fn=judge, llm_call=None,
    )
    # no judge dims -> composite = gates_component only (weight gates=1) = 1.0
    assert out["composite"] == 1.0
    assert out["judge_means"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_case_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.case_runner'`

- [ ] **Step 3: Write `src/loop_iter/case_runner.py`**

```python
from __future__ import annotations
from loop_iter.gates import load_gates, run_gates
from loop_iter.judge import judge_case as _default_judge
from loop_iter.scoring import composite, gate_pass_rates, judge_means

def run_cases(cases: list[dict], worktree: str, agent_subdir: str,
              gates_path: str, judge_md: str, weights: dict[str, float],
              run_case_fn, judge_case_fn=_default_judge, llm_call=None) -> dict:
    """Run every case through run_case_fn, then gates + judge -> RunScores.

    judge_case_fn may be injected for tests; defaults to loop_iter.judge.judge_case.
    A None judge result for a case => gates-only contribution (no synthetic dim).
    """
    gates = load_gates(gates_path)
    case_scores: list[dict] = []
    for case in cases:
        result = run_case_fn(case, worktree, agent_subdir)
        gate_results = run_gates(result, case, gates)
        judged = (judge_case_fn(result, case, judge_md, llm_call)
                  if llm_call is not None else None)
        case_scores.append({
            "case_id": case["id"],
            "gates": gate_results,
            "judge": judged or [],
            "error": result.get("error"),
        })
    return {
        "cases": case_scores,
        "composite": composite(case_scores, weights),
        "gate_pass_rates": gate_pass_rates(case_scores),
        "judge_means": judge_means(case_scores),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_case_runner.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Add CLI `__main__` blocks** — append to `src/loop_iter/case_runner.py`:

```python
def _cli():
    import argparse, json, yaml, importlib.util
    from loop_iter.state import RunPaths, append_round
    ap = argparse.ArgumentParser(prog="python -m loop_iter.case_runner")
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--agent-subdir", required=True)
    ap.add_argument("--eval", required=True, help="path to eval dir (goal.yaml etc.)")
    ap.add_argument("--adapter", required=True, help="path to adapter run_case.py")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--base", default=".")
    ap.add_argument("--round", type=int, required=True)
    a = ap.parse_args()

    ev = a.eval
    goal = yaml.safe_load(open(f"{ev}/goal.yaml"))
    cases = json.load(open(f"{ev}/cases.json"))
    spec = importlib.util.spec_from_file_location("adapter_run_case", a.adapter)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

    from loop_iter.llm_client import chat as llm_call  # Task 10 / configured later
    out = run_cases(cases, a.worktree, a.agent_subdir, f"{ev}/gates.py", open(f"{ev}/judge.md").read(),
                    goal["weights"], run_case_fn=mod.run_case, llm_call=llm_call)
    out["round"] = a.round
    rp = RunPaths(base=a.base, run_id=a.run_id)
    append_round(rp, out)
    print(json.dumps({"round": a.round, "composite": out["composite"],
                      "gate_pass_rates": out["gate_pass_rates"]}, indent=2))

if __name__ == "__main__":
    _cli()
```

- [ ] **Step 6: Commit**

```bash
git add src/loop_iter/case_runner.py tests/test_case_runner.py
git commit -m "feat: add case_runner orchestrator + CLI (run_cases -> gates+judge -> composite)"
```

---

## Task 9: goal_check CLI

**Files:**
- Create: `src/loop_iter/goal_check.py`
- Test: `tests/test_goal_check.py`

- [ ] **Step 1: Write the failing tests `tests/test_goal_check.py`**

```python
import json, yaml
from loop_iter.state import RunPaths, append_round
from loop_iter.goal_check import check_latest

def _goal(tmp_path, threshold=0.8, max_rounds=3, regression="block"):
    g = {"threshold": threshold, "max_rounds": max_rounds,
         "weights": {"gates": 1.0, "tone": 1.0}, "regression": regression}
    (tmp_path / "goal.yaml").write_text(yaml.safe_dump(g))
    return str(tmp_path / "goal.yaml")

def test_check_latest_met(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    append_round(rp, {"round": 1, "composite": 0.9,
                      "gate_pass_rates": {"exact": 1.0}, "judge_means": {}, "cases": []})
    v = check_latest(rp, _goal(tmp_path), best_gate_rates={"exact": 1.0})
    assert v["met"] is True

def test_check_latest_not_met_below_threshold(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    append_round(rp, {"round": 1, "composite": 0.5,
                      "gate_pass_rates": {"exact": 1.0}, "judge_means": {}, "cases": []})
    v = check_latest(rp, _goal(tmp_path), best_gate_rates={"exact": 1.0})
    assert v["met"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_goal_check.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.goal_check'`

- [ ] **Step 3: Write `src/loop_iter/goal_check.py`**

```python
from __future__ import annotations
import json
import yaml
from loop_iter.state import RunPaths, load_scores
from loop_iter.scoring import goal_met

def check_latest(rp: RunPaths, goal_path: str, best_gate_rates: dict | None) -> dict:
    """Read the latest round's case_scores + goal -> GoalVerdict (pure-ish; reads files)."""
    goal = yaml.safe_load(open(goal_path))
    data = load_scores(rp)
    if not data.get("rounds"):
        return {"met": False, "round": 0, "composite": 0.0,
                "gate_pass_rates": {}, "regressed_gates": [], "reason": "no rounds yet"}
    latest = data["rounds"][-1]
    v = goal_met(
        round_idx=latest["round"], case_scores=latest["cases"],
        weights=goal["weights"], threshold=goal["threshold"],
        max_rounds=goal["max_rounds"], best_gate_rates=best_gate_rates,
        regression_policy=goal.get("regression", "block"),
    )
    return v

def _cli():
    import argparse
    ap = argparse.ArgumentParser(prog="python -m loop_iter.goal_check")
    ap.add_argument("--eval", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--base", default=".")
    ap.add_argument("--best-gate-rates", default=None,
                    help="JSON of best-so-far gate pass rates; omit on round 1")
    a = ap.parse_args()
    rp = RunPaths(base=a.base, run_id=a.run_id)
    best = json.loads(a.best_gate_rates) if a.best_gate_rates else None
    v = check_latest(rp, f"{a.eval}/goal.yaml", best)
    print(json.dumps(v, indent=2))
    # exit code so run-until-done can consume it: 0 = met, 1 = not met
    raise SystemExit(0 if v["met"] else 1)

if __name__ == "__main__":
    _cli()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_goal_check.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/loop_iter/goal_check.py tests/test_goal_check.py
git commit -m "feat: add goal_check CLI (verdict + exit code for run-until-done)"
```

---

## Task 10: Toy agent + toy eval fixtures + LLM client

**Files:**
- Create: `adapters/toy/agent_files/SKILL.md`
- Create: `adapters/toy/agent_files/prompt.md`
- Create: `adapters/toy/agent_files/tools.json`
- Create: `adapters/toy/apply_variant.py`
- Create: `evals/toy-basic/goal.yaml`
- Create: `evals/toy-basic/cases.json`
- Create: `evals/toy-basic/gates.py`
- Create: `evals/toy-basic/judge.md`
- Create: `src/loop_iter/llm_client.py`

> The toy agent is deliberately tiny: a one-word-answer skill the loop can demonstrably improve. Cases ask for a single capital city / simple fact; a deliberately-vague baseline skill fails the `is_one_word` gate until the maker sharpens it.

- [ ] **Step 1: Write the toy agent baseline harness**

`adapters/toy/agent_files/SKILL.md`:
```markdown
---
name: toy-answerer
description: Answer the user's question. Keep it short.
---

# Toy Answerer

When asked a question, respond helpfully. (Baseline is deliberately vague —
the loop should sharpen this into "answer in exactly one word, no punctuation".)
```

`adapters/toy/agent_files/prompt.md`:
```markdown
You are a concise question-answerer. Answer the user's question.
```

`adapters/toy/agent_files/tools.json`:
```json
{ "tools": [] }
```

- [ ] **Step 2: Write `adapters/toy/apply_variant.py`**

```python
"""Toy adapter apply_variant: wraps loop_iter.adapter with toy-specific paths.
The toy agent's repo root IS this loop-iteration repo; its harness lives at
adapters/toy/agent_files. apply_variant stages a worktree from main."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from loop_iter.adapter import apply_variant as _apply, remove_worktree  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_SUBDIR = "adapters/toy/agent_files"

def apply_variant(baseline_ref: str = "HEAD") -> str:
    return _apply(repo_root=REPO_ROOT, baseline_ref=baseline_ref, agent_subdir=AGENT_SUBDIR)
```

- [ ] **Step 3: Write the toy eval spec**

`evals/toy-basic/goal.yaml`:
```yaml
threshold: 0.85
max_rounds: 3
regression: block
weights:
  gates: 2.0
  conciseness: 1.0
```

`evals/toy-basic/cases.json`:
```json
[
  {"id": "c1", "query": "What is the capital of France? Answer in one word.", "expected": "Paris"},
  {"id": "c2", "query": "What is the capital of Japan? Answer in one word.", "expected": "Tokyo"},
  {"id": "c3", "query": "What is 2 + 2? Answer in one word.", "expected": "Four"}
]
```

`evals/toy-basic/gates.py`:
```python
def is_one_word(result, case):
    """Output must be a single word, no punctuation."""
    out = result["output"].strip().rstrip(".!?")
    return {"passed": len(out.split()) == 1}

def matches_expected(result, case):
    """Case-insensitive match against expected (if provided)."""
    if not case.get("expected"):
        return {"passed": True}
    return {"passed": result["output"].strip().rstrip(".!?").lower() == case["expected"].lower()}

GATES = {"is_one_word": is_one_word, "matches_expected": matches_expected}
```

`evals/toy-basic/judge.md`:
```markdown
You are scoring a question-answering agent. Score the dimension:

- **conciseness** (0-10): 10 = exactly one word, no extra text, no hedging;
  0 = verbose, multi-sentence, or off-topic.
```

- [ ] **Step 4: Write `src/loop_iter/llm_client.py`**

```python
"""Thin OpenAI-compatible chat client used by the judge. Reads creds from env
(config.json writes OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL at startup
in the demo; here we just read env, no hardcoded keys)."""
from __future__ import annotations
import os
import httpx

def chat(prompt: str, model: str | None = None, timeout: float = 60.0) -> str:
    base = os.environ.get("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    key = os.environ.get("OPENAI_API_KEY", "")
    model = model or os.environ.get("OPENAI_MODEL", "glm-4.7")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.1, "max_tokens": 512},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
```

- [ ] **Step 5: Verify fixtures import/parse**

```bash
. .venv/bin/activate
python -c "import yaml,json; yaml.safe_load(open('evals/toy-basic/goal.yaml')); json.load(open('evals/toy-basic/cases.json')); print('ok')"
python -c "import importlib.util; s=importlib.util.spec_from_file_location('g','evals/toy-basic/gates.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert set(m.GATES)=={'is_one_word','matches_expected'}; print('ok')"
```
Expected: `ok` twice.

- [ ] **Step 6: Commit**

```bash
git add adapters/toy/agent_files adapters/toy/apply_variant.py evals/toy-basic src/loop_iter/llm_client.py
git commit -m "feat: add toy agent, toy-basic eval spec, and OpenAI-compatible llm client"
```

---

## Task 11: `harness-rewriter` sub-agent (maker)

**Files:**
- Create: `.claude/agents/harness-rewriter.md`

- [ ] **Step 1: Write the maker definition**

`.claude/agents/harness-rewriter.md`:
```markdown
---
name: harness-rewriter
description: The MAKER in the self-iteration loop. Given a worktree containing the current agent harness (prompt/skills/tools) and the latest round's failing gates + judge dims, rewrite the harness files to address the ROOT CAUSES — never overfit to individual cases. You edit files only; you do not run or score.
model: opus
---

# harness-rewriter (maker)

You rewrite the agent's *harness* — the files under the worktree's
`adapters/<agent>/agent_files/` (its `SKILL.md`, `prompt.md`, `tools.json`) — to fix
what the last evaluation round surfaced.

## Input (given to you)
- `worktree` — the path to a git worktree; the harness files live at `<worktree>/adapters/<agent>/agent_files/`.
- `findings` — the failing gates and weak judge dims from the last round, with per-case examples.

## How to rewrite (this is the whole job)
1. Read every harness file in the worktree's agent subdir.
2. From the findings, infer **themes** — e.g. "outputs are multi-word when one word is required",
   "hedges instead of answering", "misses expected exact match". Do NOT memorize individual cases.
3. Edit the harness files to encode the fix as a *general rule* the agent will follow on unseen cases.
   Prefer sharpening instructions in `SKILL.md`/`prompt.md` over hard-coding answers.
4. Keep edits minimal and surgical. Do not touch anything outside the agent harness subdir.

## Hard rules
- **Themes, not per-case patches.** Adding "if asked about France, say Paris" is a failure mode.
  Encode the *rule* ("answer in exactly one word, no punctuation") that makes all cases pass.
- **You do not score.** You do not run cases or gates. The checker does that next.
- **You do not edit outside the harness subdir.**
- When done, report the themes you addressed and which files you changed.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/harness-rewriter.md
git commit -m "feat: add harness-rewriter (maker) sub-agent definition"
```

---

## Task 12: `goal-checker` sub-agent (run-until-done reviewer)

**Files:**
- Create: `.claude/agents/goal-checker.md`

- [ ] **Step 1: Write the reviewer definition**

`.claude/agents/goal-checker.md`:
```markdown
---
name: goal-checker
description: The separate REVIEWER for the self-iteration loop's stop condition. You do NOT rewrite anything. You read the latest scores + the goal and decide, via a verifiable command, whether the goal is met. You are a different agent from the maker on purpose — the model that did the work never grades its own "done".
model: sonnet
---

# goal-checker (reviewer)

You decide whether the loop may stop. You are NOT the maker; you did not write the harness.
"Done" is a verifiable claim, not your opinion.

## Procedure
1. From the run state, find the latest round's scores and the eval's `goal.yaml`.
2. Run the deterministic check — do not eyeball:
   ```
   python -m loop_iter.goal_check \
     --eval evals/<goal> --run-id <run_id> \
     --best-gate-rates '<json or omit on round 1>'
   ```
   Exit code 0 = met; 1 = not met. The JSON it prints is the evidence (composite, regressions, reason).
3. Report the verdict verbatim from the command, including the `reason`.
   - If `met: true` → the loop stops; surface the best variant.
   - If `met: false` → say so and why (threshold / regression / cap). The loop continues unless `max_rounds` was hit.

## Hard rules
- **You do not edit files.** You do not rewrite the harness.
- **Evidence or it didn't happen.** Paste the command's JSON output. Do not say "looks done".
- **You are not the maker's friend.** A gate regression means not-met even if the composite rose.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/goal-checker.md
git commit -m "feat: add goal-checker (run-until-done reviewer) sub-agent"
```

---

## Task 13: `case-evaluator` skill (checker wrapper)

**Files:**
- Create: `.claude/skills/case-evaluator/SKILL.md`

- [ ] **Step 1: Write the skill**

`.claude/skills/case-evaluator/SKILL.md`:
```markdown
---
name: case-evaluator
description: The CHECKER stage of the self-iteration loop. Given a worktree holding a candidate agent harness and an eval spec, run all cases through the adapter, score them with the gates + LLM-judge, write the round's RunScores to state, and return the failing gates + weak judge dims for the maker. Use whenever the self-iterate loop needs to evaluate a candidate harness variant.
---

# case-evaluator (checker)

You evaluate one candidate harness variant and record the result. You do NOT rewrite anything.

## Inputs
- `worktree` — path to the worktree holding the candidate harness.
- `eval` — the eval dir (has `goal.yaml`, `cases.json`, `gates.py`, `judge.md`).
- `adapter` — the adapter's `run_case.py`.
- `run_id`, `round`, `base` — state location.

## Procedure
Run the deterministic evaluator (it runs cases, gates, and judge; you do not eyeball):
```
python -m loop_iter.case_runner \
  --worktree <worktree> --agent-subdir <adapters/<agent>/agent_files> \
  --eval <eval> --adapter <adapter>/run_case.py \
  --run-id <run_id> --base <base> --round <round>
```
This writes the round into `.loop/iterate/<run_id>/scores.json` and prints the composite + gate pass-rates.

## What to return to the loop driver
- The composite score and each gate's pass-rate.
- The **failing gates** and **weak judge dims**, with one example case each — this is the
  `findings` the maker (harness-rewriter) will act on. Group them as themes where obvious.

## Rules
- A case whose `run_case` errored scores 0 on gates; flag it but do not abort the round.
- If the judge failed for a case (no dims returned), note it — that case is gates-only this round.
- You record; you do not decide whether the goal is met (that's goal-checker's job).
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/case-evaluator/SKILL.md
git commit -m "feat: add case-evaluator (checker) skill"
```

---

## Task 14: `self-iterate` skill (one round) + run driver doc

**Files:**
- Create: `.claude/skills/self-iterate/SKILL.md`

- [ ] **Step 1: Write the skill**

`.claude/skills/self-iterate/SKILL.md`:
```markdown
---
name: self-iterate
description: Drives ONE round of agent-harness self-iteration. Read state → stage a candidate variant worktree → dispatch the harness-rewriter (maker) to fix last round's failures → dispatch the case-evaluator (checker) to score it → snapshot the variant and update state → report findings + whether the goal-checker says met. The loop itself is run-until-done (ralph/autopilot) wrapping this skill; goal-checker is the separate reviewer. Use when the user says "self-iterate <agent> toward <goal>" or when run-until-done fires a round.
---

# self-iterate (one round)

You run exactly one round. The broader loop (repeating until the goal is met) is driven by
run-until-done — you do not loop yourself.

## Inputs (from the loop driver / user)
- `agent` — adapter name under `adapters/` (e.g. `toy`).
- `goal` — eval name under `evals/` (e.g. `toy-basic`).
- `run_id` — the current run's id (timestamp+hex).
- `round` — this round's number (1-based).

## One round
1. **Read state.** Open `.loop/iterate/<run_id>/scores.json`. On round 1 there are no prior
   findings; on round N>1 the maker needs last round's failing gates + weak dims.
2. **Stage the variant.** Run the adapter's `apply_variant` to get an isolated worktree from the
   baseline (HEAD). The maker will edit the harness there; source is never touched mid-loop.
   ```
   python -c "import sys; sys.path.insert(0,'adapters/<agent>'); import apply_variant as a; print(a.apply_variant())"
   ```
   Capture the printed worktree path.
3. **Maker.** Dispatch the `harness-rewriter` sub-agent with the worktree + last round's findings
   (round 1: findings = "cold start, sharpen the baseline harness to satisfy the gates"). It edits
   the harness files in the worktree.
4. **Checker.** Dispatch the `case-evaluator` skill on the worktree (eval = `evals/<goal>`). It
   writes this round's RunScores to state and returns failing gates + weak dims.
5. **Snapshot + state.** Copy the variant's harness subdir to
   `.loop/iterate/<run_id>/variants/round_<N>/` (provenance). Append a one-line summary to
   `.loop/iterate/<run_id>/progress.md` (round N: composite, best so far).
6. **Stop-condition handoff.** Run the goal-checker:
   ```
   python -m loop_iter.goal_check --eval evals/<goal> --run-id <run_id> \
     --best-gate-rates '<best so far, or omit on round 1>'
   ```
   Report its verdict. If `met`, surface the best variant (which `variants/round_*` won) and stop.
   If not met and under `max_rounds`, return the findings so run-until-done fires round N+1.

## How to drive the whole loop (run-until-done)
Wrap this skill in **ralph / autopilot** (OMC): the *worker* is "run one self-iterate round for
`<agent>` toward `<goal>`", and the *verification reviewer* is the `goal-checker` sub-agent. The
stop condition (composite ≥ threshold, no gate regression, ≤ max_rounds) is the reviewer's check,
judged by an agent that did NOT do the work — the maker/checker split applied to the stop condition.

For interactive control, run single rounds by hand and read `progress.md` between them.

## Rules
- One round only. Do not loop.
- The maker and the checker are different agents. You are the orchestrator, neither.
- Source repo is never mutated mid-loop — only the worktree. Merging the winner is the human's call.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/self-iterate/SKILL.md
git commit -m "feat: add self-iterate skill (one round) + run-until-done driver notes"
```

---

## Task 15: Golden-round integration test (deterministic, with stubs)

**Files:**
- Create: `tests/test_golden_round.py`

> Proves the *machinery* loop end-to-end deterministically: a stub `run_case` that improves once
> the maker's "fix" is applied, a stub maker that flips a flag when guided by failing gates, real
> scoring/goal_met/state. Asserts composite rises, goal eventually met, and a regression is blocked.

- [ ] **Step 1: Write the test `tests/test_golden_round.py`**

```python
from loop_iter.state import RunPaths, append_round, load_scores
from loop_iter.scoring import goal_met

def test_golden_round_score_rises_until_goal_met(tmp_path):
    """Two rounds: round 1 fails is_one_word (multi-word output); after the maker
    'sharpens' the skill, round 2 outputs one word -> gate passes, composite >= threshold."""
    rp = RunPaths(base=str(tmp_path), run_id="golden")

    cases = [{"id": "c1", "query": "q", "expected": None},
             {"id": "c2", "query": "q", "expected": None}]

    def cs(gates_passed, judge_score):
        return [{"case_id": c["id"],
                 "gates": [{"gate": "is_one_word", "passed": gates_passed}],
                 "judge": [{"dim": "conciseness", "score": judge_score}],
                 "error": None} for c in cases]

    weights = {"gates": 2.0, "conciseness": 1.0}

    # Round 1: maker hasn't sharpened yet -> multi-word -> gate fails
    r1 = {"round": 1, "cases": cs(gates_passed=False, judge_score=3.0),
          "gate_pass_rates": {"is_one_word": 0.0}, "judge_means": {"conciseness": 3.0}}
    from loop_iter.scoring import composite
    r1["composite"] = composite(r1["cases"], weights)
    append_round(rp, r1)

    v1 = goal_met(1, r1["cases"], weights, threshold=0.85, max_rounds=3,
                  best_gate_rates=None, regression_policy="block")
    assert v1["met"] is False  # gate fails + composite low

    # Round 2: maker sharpened -> one word -> gate passes
    r2 = {"round": 2, "cases": cs(gates_passed=True, judge_score=10.0),
          "gate_pass_rates": {"is_one_word": 1.0}, "judge_means": {"conciseness": 10.0}}
    r2["composite"] = composite(r2["cases"], weights)
    append_round(rp, r2)

    best_gate = {"is_one_word": 1.0}  # best so far is round 2
    v2 = goal_met(2, r2["cases"], weights, threshold=0.85, max_rounds=3,
                  best_gate_rates=best_gate, regression_policy="block")
    assert v2["met"] is True          # gate 1.0, composite high, no regression
    assert v2["composite"] >= 0.85

    # best_round tracking
    assert load_scores(rp)["best_round"] == 2


def test_golden_round_regression_is_blocked(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="reg")
    cases = [{"id": "c1", "query": "q", "expected": None}]
    weights = {"gates": 2.0, "conciseness": 1.0}
    from loop_iter.scoring import composite

    best = {"is_one_word": 1.0}  # previously achieved perfect gate
    # Now a candidate that regresses the gate (0.0) but a great judge score
    reg_cases = [{"case_id": "c1",
                  "gates": [{"gate": "is_one_word", "passed": False}],
                  "judge": [{"dim": "conciseness", "score": 10.0}], "error": None}]
    comp = composite(reg_cases, weights)
    v = goal_met(2, reg_cases, weights, threshold=0.5, max_rounds=3,
                 best_gate_rates=best, regression_policy="block")
    assert v["regressed_gates"] == ["is_one_word"]
    assert v["met"] is False  # blocked despite composite possibly >= threshold
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (scoring 9, gates 3, judge 3, adapter 3, run_case 1, state 4, case_runner 2, goal_check 2, golden 2 = 29 passed; + smoke 1).

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_round.py
git commit -m "test: add golden-round integration (score rises, goal met, regression blocked)"
```

---

## Task 16: User guide + live-loop manual verification

**Files:**
- Modify: `README.md` (append "Self-iteration loop" section)

- [ ] **Step 1: Append a user-guide section to `README.md`**

Append:
```markdown

## Self-iteration loop (the product)

This repo *is* an agent-harness self-iteration loop. It iterates an agent's harness
(prompt/skills/tools) until a verifiable goal is met. See
[the design](docs/superpowers/specs/2026-06-23-self-iteration-loop-design.md).

### Run it on the toy agent (dogfood)

```bash
. .venv/bin/activate
export OPENAI_API_KEY=...      # for the LLM judge
export OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
export OPENAI_MODEL=glm-4.7

# One round, interactively (read state, stage worktree, maker, checker, goal-check):
#   tell Claude Code: "self-iterate toy toward toy-basic, run_id $(date +%Y%m%d_%H%M%S)_toy"

# Unattended (run-until-done until the goal is met):
#   use ralph/autopilot with self-iterate as the worker and goal-checker as the reviewer
```

State lands in `.loop/iterate/<run_id>/` (`progress.md`, `scores.json`, `variants/round_N/`).
The loop never auto-merges — review `report.md` and merge the winning variant yourself.

### Point it at your own agent

1. **Adapter** — `adapters/<my-agent>/{run_case.py, apply_variant.py, agent_files/}`
   (copy `adapters/toy/` and change `run_case` to invoke your agent).
2. **Goal** — `evals/<my-goal>/{goal.yaml, cases.json, gates.py, judge.md}`
   (copy `evals/toy-basic/` and edit the gates/rubric/threshold).
3. **Run** — in Claude Code: "self-iterate `<my-agent>` toward `<my-goal>`".
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add self-iteration loop user guide and run instructions"
```

- [ ] **Step 3: Manual live verification (record result in `.loop/progress.md`)**

With the venv active and `OPENAI_*` set, run a single real round against the toy agent to confirm
the live path works (real `claude` in the worktree + real LLM judge). This is a manual check, not
automated — write the outcome into `.loop/progress.md` → Done:
- Confirm `apply_variant` produced a worktree.
- Confirm `case_runner` wrote a `scores.json` with a composite.
- Confirm `goal_check` returned a verdict with exit code.

If anything fails here, the fix is a new task — do not mark the plan done with a red live check.

---

## Self-Review (completed during authoring)

**1. Spec coverage:**
- §4.1 three seams → Tasks 5-6 (adapter), 10 (eval spec), 5 (variant+worktree). ✓
- §4.2 four components → Tasks 11 (maker), 13 (checker), 12 (goal-checker), 14 (self-iterate). ✓
- §4.3 one-round data flow → Task 14 steps 1-6 map 1:1. ✓
- §4.4 state layout → Task 7 (RunPaths: progress.md, scores.json, variants/). ✓
- §4.5 user workflow → Task 16. ✓
- §4.6 error handling → gate fault-tolerance (Task 3), judge fallback (Task 4), run_case crash-safe (Task 6), regression block (Task 2/9), max_rounds cap (Task 2), worktree cleanup (Task 5). ✓
- §4.7 testing → pure-fn unit tests (Task 2), gate contract (3), judge fallback (4), hermetic adapter (5), state roundtrip (7), case_runner stubs (8), goal_check (9), golden round (15). ✓
- §5 scope (in/out) → minimal in-scope all covered; maas/web/FastAPI explicitly not built. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling". Every code step shows full code. The only
environment-specific values (`OPENAI_*`, `run_id` timestamp) are documented as runtime inputs, not
placeholders. The Task 8 CLI references `loop_iter.llm_client` which Task 10 creates — order is
fine (Task 8's CLI is exercised live only after Task 10).

**3. Type/name consistency:** `RunScores` keys (`composite`, `gate_pass_rates`, `judge_means`,
`cases`, `round`) are identical in scoring (Task 2), case_runner (8), state (7), goal_check (9),
golden (15). `goal_met` signature is constant across Task 2 def, Task 9 use, Task 15 use. Gate
module contract `GATES = {name: fn(result, case) -> {passed}}` is constant in Task 3, 10, and the
skill (13). `RunPaths(base, run_id)` constant in Tasks 7/9/15.

**Note on Task 8 ↔ Task 10 ordering:** the `case_runner` CLI imports `loop_iter.llm_client`, which
is created in Task 10. The unit tests for case_runner (Task 8) inject a stub `llm_call=None` path,
so they pass before Task 10. The CLI is only run live in Task 16, after Task 10. No reordering
needed; flagging so the executor doesn't trip on it.
