# self-iterate harness-quality guardrail — Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a harness-quality dimension as a **guardrail + tiebreak** (not a main objective): each round the harness files are scored against a `quality.md` rubric; a round whose quality regresses below baseline (− tolerance) cannot satisfy `met` and cannot be selected as best; equal-composite rounds are broken by higher quality. Quality never enters the composite.

**Architecture:** `judge.py` gains `judge_quality(harness_text, quality_md, llm_call)` (mirrors `judge_case`'s LLM-call + degrade-to-None contract). `adapter_generic.py` gains `harness_text(eval_dir, repo_root, read_root)` to concatenate the harness files from a given root. The `baseline` and `case-run` cli commands each compute a quality score (when `quality.md` is present) and persist it (`baseline.json` → `state.baseline_quality`; per-round `quality.json` + a `quality` field on the scores.json round entry). `goal_check.check_and_advance` adds the guardrail (quality regression blocks `met`) and a quality-aware `recompute_best` (tiebreak + exclusion). quality is opt-in per goal: no `quality.md` → no quality call, guardrail inactive, fully backward-compatible.

**Tech Stack:** Python 3.11+, pytest, stdlib `json`/`pathlib`.

**Spec:** [docs/superpowers/specs/2026-06-24-self-iterate-setup-and-loop-design.md](../specs/2026-06-24-self-iterate-setup-and-loop-design.md) §3.5 / D5.

**Parallelism note (deliberate simplification):** the spec says case-eval and quality-judge run "in parallel". This plan computes quality **sequentially inside `case-run`** (one extra LLM call after the N case calls) — true concurrency is deferred (YAGNI; quality is 1 call vs N case calls, and threading inside the cli adds complexity for little gain). The guardrail *semantics* (regression + tiebreak) are what matter and are fully implemented.

---

## File Structure

```
scripts/loop_iter/judge.py            MODIFY — add judge_quality + quality_mean
scripts/loop_iter/adapter_generic.py  MODIFY — add harness_text
scripts/loop_iter/state.py            MODIFY — add recompute_best
scripts/loop_iter/goal_check.py       MODIFY — check_and_advance: quality guardrail + best via recompute_best
scripts/loop_iter/cli.py              MODIFY — baseline + case-run compute quality; write quality.json
tests/test_judge.py                   APPEND — judge_quality + quality_mean
tests/test_state.py                   APPEND — recompute_best (tiebreak + exclusion)
tests/test_goal_check.py              APPEND — quality guardrail blocks met
tests/test_cli.py                     APPEND — baseline + case-run write quality
examples/toy/.self-iterate/toy-basic/ ADD quality.md (template)
skills/self-iterate/SKILL.md          MODIFY — note optional quality.md
README.md                             MODIFY — note quality.md guardrail
```

**Signatures:**
- `judge.judge_quality(harness_text: str, quality_md: str, llm_call, model="glm-4.7") -> list[dict] | None`
- `judge.quality_mean(dims: list[dict] | None) -> float | None`
- `adapter_generic.harness_text(eval_dir: str, repo_root: str, read_root: str) -> str`
- `state.recompute_best(rp, baseline_quality: float | None, tolerance: float) -> int | None`

**Quality data shapes:**
- `baseline.json`: gains `"quality": <float|null>` + `"quality_dims": [...]`.
- `state.json`: uses existing `baseline_quality` field (init None).
- per-round `quality.json`: `{"round": N, "quality": <float|null>, "quality_dims": [...]}`.
- scores.json round entry: gains `"quality": <float|null>`.

**Guardrail semantics:**
- `quality_regressed = (baseline_quality is not None and round_quality is not None and round_quality < baseline_quality - tolerance)`.
- In `check_and_advance`: if `quality_regressed` and `v["met"]` → force `v["met"]=False`, reason `"quality regression: ..."`.
- `recompute_best`: eligible = rounds not quality-regressed (None quality → eligible); fallback to all if none eligible; best = `max(eligible, key=(composite, quality or -1))`.

---

## Task 1: `judge_quality` + `quality_mean` + `harness_text` + `quality.md` template

**Files:**
- Modify: `scripts/loop_iter/judge.py`
- Modify: `scripts/loop_iter/adapter_generic.py`
- Create: `examples/toy/.self-iterate/toy-basic/quality.md`
- Test: `tests/test_judge.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_judge.py`:**

```python
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
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_judge.py -q` → expect FAIL (`ImportError: cannot import name judge_quality`).

- [ ] **Step 3: Add to `scripts/loop_iter/judge.py`** (after `judge_case`):

```python
def quality_mean(dims: list[dict] | None) -> float | None:
    """Mean dim score (0-10), or None if no dims (gates-only / degraded signal)."""
    if not dims:
        return None
    return sum(d["score"] for d in dims) / len(dims)


def judge_quality(harness_text: str, quality_md: str, llm_call,
                  model: str = "glm-4.7") -> list[dict] | None:
    """Ask the LLM to score the harness FILES per the quality rubric. Returns [{dim, score}] or None.

    Same degrade-to-None contract as judge_case: unparseable output (strict JSON, one retry, then
    degrade) AND any llm_call exception -> None. A flaky quality-judge never crashes the round; the
    guardrail simply goes inactive (treated as no quality signal) for that round. No rubric -> None
    without calling the LLM. llm_call(prompt, model) -> str."""
    if not quality_md:
        return None
    prompt = (
        f"{quality_md}\n\n"
        f"Return ONLY strict JSON: {{\"dims\": [{{\"dim\": <name>, \"score\": <0-10>}}]}}.\n"
        f"Harness files (concatenated):\n{harness_text}\n"
    )
    for _ in range(2):  # initial + one retry
        try:
            dims = _parse_dims(llm_call(prompt, model))
        except Exception:  # network/timeout/transport -> degrade, never crash
            dims = None
        if dims is not None:
            return dims
    return None
```

- [ ] **Step 4: Add `harness_text` to `scripts/loop_iter/adapter_generic.py`** (after `resolve_harness`):

```python
def harness_text(eval_dir: str, repo_root: str, read_root: str) -> str:
    """Concatenate the harness files (resolved against repo_root) read from read_root, each headed
    with `### <rel>`. Used to feed the quality-judge. Missing files are skipped."""
    harness = resolve_harness(eval_dir, repo_root)
    parts = []
    for rel in harness:
        p = Path(read_root, rel)
        if p.exists():
            parts.append(f"### {rel}\n{p.read_text()}")
    return "\n\n".join(parts)
```

(`Path` is already imported at the top of adapter_generic.py — verify; if not, add `from pathlib import Path`.)

- [ ] **Step 5: Create `examples/toy/.self-iterate/toy-basic/quality.md`:**

```markdown
# Harness quality rubric

Score the agent's harness file(s) (the prompt/instructions shown) on these dimensions, 0-10:

- **clarity** (0-10): 10 = unambiguous, well-structured instructions a model can follow directly;
  0 = vague, contradictory, or confusing.
- **no_overfit** (0-10): 10 = general rules that transfer to unseen cases; 0 = hardcodes specific
  eval answers or case-specific hacks.
- **maintainability** (0-10): 10 = concise, readable, easy to edit; 0 = bloated, repetitive, or brittle.
```

- [ ] **Step 6:** `.venv/bin/pytest tests/test_judge.py -q` → all pass. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 7: Commit:**
```bash
git add scripts/loop_iter/judge.py scripts/loop_iter/adapter_generic.py examples/toy/.self-iterate/toy-basic/quality.md tests/test_judge.py
git commit -m "feat: judge_quality + quality_mean + harness_text + toy quality.md template"
```

---

## Task 2: `baseline` computes `baseline_quality`

**Files:**
- Modify: `scripts/loop_iter/cli.py` (`_baseline`)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing test to `tests/test_cli.py`:**

```python
def test_cli_baseline_computes_quality_when_quality_md_present(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("rubric: be clear")
    rp = RunPaths(base=str(repo), run_id="r1")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda text, md, llm_call, model="glm-4.7":
        [{"dim": "clarity", "score": 8.0}])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    st = load_state(rp)
    assert st["baseline_quality"] == 8.0
    import json
    assert json.loads(rp.baseline_file.read_text())["quality"] == 8.0


def test_cli_baseline_skips_quality_when_no_quality_md(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    # NO quality.md
    rp = RunPaths(base=str(repo), run_id="r1")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    def boom(*a, **k):
        raise AssertionError("judge_quality must not be called without quality.md")
    monkeypatch.setattr(jm, "judge_quality", boom)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    assert load_state(rp)["baseline_quality"] is None
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (baseline doesn't compute quality).

- [ ] **Step 3: Modify `_baseline` in `scripts/loop_iter/cli.py`.** After `out = run_cases(...)` and before `rp.baseline_file.write_text(...)`, compute quality. The current `_baseline` body (read it first) builds `out` then writes baseline_file then `advance_phase(... updates={"round": 1, "baseline_composite": out["composite"]})`. Insert quality computation and add `baseline_quality` to the advance updates:

```python
    out = run_cases(cases, args.base, str(ev / "gates.py"),
                    (ev / "judge.md").read_text(), goal["weights"],
                    run_case_fn=rc, llm_call=llm_call)
    # harness-quality guardrail (opt-in via quality.md)
    quality_md_path = ev / "quality.md"
    if quality_md_path.exists():
        from loop_iter.judge import judge_quality, quality_mean
        from loop_iter.adapter_generic import harness_text
        qdims = judge_quality(harness_text(args.eval, args.base, args.base),
                              quality_md_path.read_text(), llm_call)
        out["quality"] = quality_mean(qdims)
        out["quality_dims"] = qdims or []
    else:
        out["quality"] = None
        out["quality_dims"] = []
    rp.baseline_file.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    advance_phase(rp, "baseline", "maker",
                  updates={"round": 1, "baseline_composite": out["composite"],
                           "baseline_quality": out["quality"]})
    print(json.dumps({"baseline_composite": out["composite"],
                      "baseline_quality": out["quality"], "phase": "maker", "round": 1}))
```

(Preserve the existing `rp.run_dir.mkdir(...)` and `load_state` phase guard above this. The `print` now includes `baseline_quality`.)

- [ ] **Step 4:** `.venv/bin/pytest tests/test_cli.py -q` → the 2 new tests pass. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: baseline computes baseline_quality when quality.md present"
```

---

## Task 3: `case-run` computes per-round quality

**Files:**
- Modify: `scripts/loop_iter/cli.py` (`_case_run`)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing test to `tests/test_cli.py`:**

```python
def test_cli_case_run_writes_quality_when_quality_md_present(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state, load_scores
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("rubric: be clear")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda text, md, llm_call, model="glm-4.7":
        [{"dim": "clarity", "score": 7.0}])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo),
              "--run-id", "r1", "--base", str(repo), "--round", "1"])
    # quality.json written
    import json
    q = json.loads((rp.run_dir / "quality.json").read_text())
    assert q["round"] == 1 and q["quality"] == 7.0
    # round entry in scores.json carries quality
    assert load_scores(rp)["rounds"][-1]["quality"] == 7.0
    assert load_state(rp)["phase"] == "goalcheck"
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (case-run doesn't write quality.json).

- [ ] **Step 3: Modify `_case_run` in `scripts/loop_iter/cli.py`.** Read the current `_case_run` first. It (after the Task-3 reorder) guards phase, runs `run_cases` → `out`, sets `out["round"]`, appends, advances eval→goalcheck. Insert quality computation after `out = run_cases(...)` (and after `out["round"] = args.round`), before `append_round`. The `ev` variable and `llm_call` are already in scope in `_case_run` (verify; if `ev` is named differently, adapt — it's `ev = Path(args.eval)` near the top of `_case_run`).

```python
    out["round"] = args.round
    # harness-quality guardrail (opt-in via quality.md)
    quality_md_path = ev / "quality.md"
    if quality_md_path.exists():
        from loop_iter.judge import judge_quality, quality_mean
        from loop_iter.adapter_generic import harness_text
        qdims = judge_quality(harness_text(args.eval, args.base, args.worktree),
                              quality_md_path.read_text(), llm_call)
        out["quality"] = quality_mean(qdims)
        out["quality_dims"] = qdims or []
        (rp.run_dir / "quality.json").write_text(
            json.dumps({"round": args.round, "quality": out["quality"],
                        "quality_dims": qdims or []}, indent=2, ensure_ascii=False))
    else:
        out["quality"] = None
    append_round(rp, out)
```

Note: `harness_text(args.eval, args.base, args.worktree)` reads the harness files from the **worktree** (the variant being scored), not the repo root — that's the whole point (score the variant's harness). Place this block so `append_round(rp, out)` is called once on every path (the existing if/else structure around append_round from Task 3's reorder must be preserved — read the current code and integrate so `append_round` runs exactly once after quality is attached).

- [ ] **Step 4:** `.venv/bin/pytest tests/test_cli.py -q` → the new test passes. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: case-run computes per-round quality + writes quality.json"
```

---

## Task 4: `recompute_best` + goal_check quality guardrail

**Files:**
- Modify: `scripts/loop_iter/state.py` (add `recompute_best`)
- Modify: `scripts/loop_iter/goal_check.py` (`check_and_advance`: guardrail + best via recompute_best)
- Test: `tests/test_state.py` (append), `tests/test_goal_check.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_state.py`:**

```python
from loop_iter.state import recompute_best

def test_recompute_best_tiebreak_by_quality(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    append_round(rp, {"round": 1, "composite": 0.8, "quality": 6.0, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    append_round(rp, {"round": 2, "composite": 0.8, "quality": 9.0, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    assert recompute_best(rp, baseline_quality=None, tolerance=0.5) == 2   # higher quality wins tie
    assert load_scores(rp)["best_round"] == 2

def test_recompute_best_excludes_quality_regressed(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    append_round(rp, {"round": 1, "composite": 0.7, "quality": 8.0, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    append_round(rp, {"round": 2, "composite": 0.95, "quality": 4.0, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    # baseline_quality 8.0, tol 0.5 -> round 2 (4.0 < 7.5) is regressed -> excluded; best = round 1
    assert recompute_best(rp, baseline_quality=8.0, tolerance=0.5) == 1
    assert load_scores(rp)["best_round"] == 1

def test_recompute_best_no_quality_falls_back_to_composite(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    append_round(rp, {"round": 1, "composite": 0.4, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    append_round(rp, {"round": 2, "composite": 0.8, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    assert recompute_best(rp, baseline_quality=None, tolerance=0.5) == 2
```

- [ ] **Step 2: Append failing tests to `tests/test_goal_check.py`:**

```python
def test_check_and_advance_quality_regression_blocks_met(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1, "baseline_quality": 8.0})
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 4.0, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path, threshold=0.8, max_rounds=3), None)
    assert v["met"] is False                      # composite 0.9 >= 0.8 BUT quality regressed
    assert "quality regression" in v["reason"]
    st = load_state(rp)
    assert st["phase"] == "maker" and st["round"] == 2   # not met, under cap -> loop

def test_check_and_advance_quality_ok_when_above_baseline(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1, "baseline_quality": 6.0})
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 7.0, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path, threshold=0.8, max_rounds=3), None)
    assert v["met"] is True                       # composite met AND quality 7.0 >= 6.0-0.5
    assert load_state(rp)["phase"] == "done"

def test_check_and_advance_no_baseline_quality_skips_guardrail(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1})  # baseline_quality None
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 4.0, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path, threshold=0.8, max_rounds=3), None)
    assert v["met"] is True                       # no baseline_quality -> guardrail inactive
```

- [ ] **Step 3:** `.venv/bin/pytest tests/test_state.py tests/test_goal_check.py -q` → expect FAIL.

- [ ] **Step 4: Add `recompute_best` to `scripts/loop_iter/state.py`** (after `append_round`):

```python
def recompute_best(rp: RunPaths, baseline_quality: float | None, tolerance: float) -> int | None:
    """Quality-aware best-round selection: exclude quality-regressed rounds (quality below
    baseline - tolerance), then pick max by (composite, quality). Falls back to all rounds if
    every round regresses. None quality (no signal) is never regressed. Writes best_round back
    to scores.json and returns the best round number (or None if no rounds)."""
    data = _load_raw(rp)
    rounds = data.get("rounds", [])
    if not rounds:
        return None

    def regressed(r):
        q = r.get("quality")
        return (baseline_quality is not None and q is not None
                and q < baseline_quality - tolerance)

    eligible = [r for r in rounds if not regressed(r)] or rounds
    best = max(eligible, key=lambda r: (r["composite"],
                                        r["quality"] if r.get("quality") is not None else -1.0))
    data["best_round"] = best["round"]
    write_scores(rp, data)
    return best["round"]
```

- [ ] **Step 5: Modify `check_and_advance` in `scripts/loop_iter/goal_check.py`.** Read the current `check_and_advance` first. After `v = check_latest(rp, goal_path, best_gate_rates)` and BEFORE the phase-transition if/elif/else, add the quality guardrail. Then, after the phase transition + before populating `st["best"]`, call `recompute_best` and use its result for `st["best"]` (replacing the old `max(rounds, key=composite)` best-population from Plan 1's Fix 1). Concretely, the function becomes:

```python
def check_and_advance(rp: RunPaths, goal_path: str, best_gate_rates: dict | None) -> dict:
    """State-machine goal-check: compute verdict, then advance phase.
    met -> done (met=true); not met & round < max_rounds -> maker + round++;
    not met & round >= max_rounds -> done (met=false). Refuses if phase != goalcheck.
    Quality guardrail: if baseline_quality is set and this round's quality regressed below
    baseline - tolerance, met is forced False (even if composite met). Quality never enters
    the composite; it only gates met and breaks ties in best selection."""
    goal = yaml.safe_load(open(goal_path))
    st = load_state(rp)
    if st["phase"] != "goalcheck":
        raise RuntimeError(f"phase guard: goalcheck requires phase=goalcheck, got {st['phase']!r}")
    v = check_latest(rp, goal_path, best_gate_rates)
    # quality guardrail
    tol = goal.get("quality_tolerance", 0.5)
    bq = st.get("baseline_quality")
    rounds = load_scores(rp).get("rounds", [])
    latest_q = rounds[-1].get("quality") if rounds else None
    if bq is not None and latest_q is not None and latest_q < bq - tol:
        if v["met"]:
            v["met"] = False
            v["reason"] = (f"quality regression: {latest_q:.2f} < baseline {bq:.2f} "
                           f"- tol {tol}")
    # phase transition
    if v["met"]:
        st["met"] = True
        st["phase"] = "done"
    elif st["round"] >= goal["max_rounds"]:
        st["met"] = False
        st["phase"] = "done"
    else:
        st["met"] = False
        st["round"] = st["round"] + 1
        st["phase"] = "maker"
    st["updated_at"] = _now()
    write_state(rp, st)
    # best selection: quality tiebreak + exclude regressed
    best_round = recompute_best(rp, bq, tol)
    if st["phase"] == "done" and best_round is not None:
        data = load_scores(rp)
        br = next(r for r in data["rounds"] if r["round"] == best_round)
        st["best"] = {"round": br["round"], "composite": br["composite"], "worktree": None}
        write_state(rp, st)
    v["phase"] = st["phase"]
    return v
```

(Add `from loop_iter.state import recompute_best` to goal_check.py's existing `from loop_iter.state import ...` line. `load_scores` is already imported.)

- [ ] **Step 6:** `.venv/bin/pytest tests/test_state.py tests/test_goal_check.py -q` → all pass. Then `.venv/bin/pytest -q` → full suite green. (The Plan-1 e2e test `test_e2e_state_machine_full_flow` has no quality.md → guardrail inactive → still passes; verify.)

- [ ] **Step 7: Commit:**
```bash
git add scripts/loop_iter/state.py scripts/loop_iter/goal_check.py tests/test_state.py tests/test_goal_check.py
git commit -m "feat: quality guardrail blocks met + quality-aware best selection"
```

---

## Task 5: skill + README note quality.md

**Files:**
- Modify: `skills/self-iterate/SKILL.md`
- Modify: `README.md`

- [ ] **Step 1: In `skills/self-iterate/SKILL.md`**, in the `## Loop` section after step 2 (baseline), add a short note about quality. Insert after the baseline bullet:

```markdown
   *(If `.self-iterate/<goal>/quality.md` exists, the baseline and each `case-run` also score the
   harness files themselves on a quality rubric → `baseline_quality` / per-round `quality.json`. A
   round whose quality regresses below `baseline_quality − quality_tolerance` (default 0.5) cannot
   satisfy `met` and cannot be the best variant — the guardrail against overfitting/harness rot.
   No `quality.md` → guardrail inactive.)*
```

- [ ] **Step 2: In `README.md`**, in the `### Use it on your agent` eval-spec listing, add `quality.md` as an optional file. After the `judge.md` line in the code block, add:

```markdown
  judge.md      # your LLM-rubric dims
  quality.md    # OPTIONAL — rubric judging the harness FILES themselves (guardrail: a round whose
                #            quality regresses below baseline can't satisfy the goal or be the winner)
```

- [ ] **Step 3:** No tests affected (docs). Run `.venv/bin/pytest -q` to confirm still green.

- [ ] **Step 4: Commit:**
```bash
git add skills/self-iterate/SKILL.md README.md
git commit -m "docs: note optional quality.md guardrail in skill + README"
```

---

## Self-Review (completed during authoring)

**1. Spec coverage (Plan 2's slice = §3.5 / D5):**
- `quality.md` rubric judging harness files → Task 1 (template + judge_quality). ✓
- quality-judge reuses judge.py machinery, 0-10, → quality.json → Task 1 + Task 3. ✓
- baseline quality → Task 2. ✓
- guardrail: quality < baseline − tolerance → rejects (no met, no best) → Task 4. ✓
- tiebreak: equal composite → higher quality → Task 4 (recompute_best). ✓
- quality NOT in composite → composite unchanged (Tasks 2/3 only ADD a `quality` field; `scoring.composite` untouched). ✓
- opt-in (no quality.md → inactive, backward compat) → Tasks 2/3/4 all gate on quality.md / None. ✓

**2. Placeholder scan:** No TBD/TODO. Every code step shows full code. The `_case_run` integration note ("integrate so append_round runs exactly once") is concrete — it references the existing Task-3 reorder structure the implementer must read.

**3. Type consistency:** `judge_quality(harness_text, quality_md, llm_call, model="glm-4.7") -> list|None` consistent in Task 1 (def + tests) and Task 2/3 calls. `quality_mean(dims) -> float|None` consistent. `harness_text(eval_dir, repo_root, read_root) -> str` consistent (Task 1 def + Task 2/3 calls: baseline uses read_root=args.base; case-run uses read_root=args.worktree). `recompute_best(rp, baseline_quality, tolerance) -> int|None` consistent (Task 4 def + tests + goal_check call). `out["quality"]` / `out["quality_dims"]` shape consistent across baseline (Task 2) and case-run (Task 3) and recompute_best (Task 4 reads `r.get("quality")`). `quality_tolerance` default 0.5 consistent (Task 4 + spec D5). `baseline_quality` field (state.json, from Plan 1 init_state) read in Task 4. The Plan-1 `st["best"]` population (Fix 1) is replaced by the recompute_best-driven population in Task 4 — verify the implementer removes the old `max(rounds, key=composite)` block to avoid double-write (the Task 4 code shows the full replacement).

**Backward compat:** Plan 1's e2e test (no quality.md) and all existing tests must stay green — quality is opt-in and None-safe throughout. The Task 4 verification step calls this out explicitly.
