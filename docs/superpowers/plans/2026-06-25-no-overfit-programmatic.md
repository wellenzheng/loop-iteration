# Programmatic no_overfit quality dim — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `no_overfit` quality dimension **programmatic and reliable** (no LLM), so the quality guardrail keeps a real signal even when the flaky LLM quality-judge degrades to None (the gap found dogfooding Plan 2 on maas).

**Architecture:** New `quality_prog.no_overfit_score(harness_text, cases) -> float` (0-10) detects whether the harness hardcodes eval-specific content: a case's `expected` answer (len>=3) or a distinctive (len>=8) substring of its `query` appearing verbatim (case-insensitive) in the harness. The cli quality computation is refactored into a shared `_compute_quality(ev, repo_root, read_root, cases, llm_call)` helper that combines the programmatic `no_overfit` (always reliable) + the LLM dims from `quality.md` (degradable, with any LLM `no_overfit` overridden by the programmatic value). `quality.md` opt-in is preserved (no quality.md → no quality). When the LLM degrades, `no_overfit` alone still yields a non-None quality → the guardrail can fire on hardcoded-answer regressions.

**Tech Stack:** Python 3.11+, pytest, stdlib only.

**Spec basis:** refinement of [Plan 2](2026-06-25-self-iterate-quality-guardrail.md) §3.5/D5, addressing the 2026-06-25 maas dogfood finding (quality-judge degrades → guardrail inert).

---

## File Structure

```
scripts/loop_iter/quality_prog.py   CREATE — no_overfit_score
scripts/loop_iter/cli.py            MODIFY — _compute_quality helper; rewire _baseline + _case_run
tests/test_quality_prog.py          CREATE — no_overfit_score tests
tests/test_cli.py                   MODIFY — update existing quality tests for combined dims; add reliable-when-degraded test
examples/toy/.self-iterate/toy-basic/quality.md  MODIFY — note no_overfit is auto-detected
skills/self-iterate/SKILL.md        MODIFY — note no_overfit is programmatic
```

**Signatures:**
- `quality_prog.no_overfit_score(harness_text: str, cases: list[dict]) -> float`
- `cli._compute_quality(ev: Path, repo_root: str, read_root: str, cases: list[dict], llm_call) -> tuple[float | None, list[dict]]`

**Semantics:**
- `no_overfit_score`: 10.0 when no eval-specific content detected; `10 * (1 - hardcoded/len(cases))` otherwise. `hardcoded` counts cases where `str(expected)` (len>=3) OR `str(query)` (len>=8) appears in `harness_text` (case-insensitive).
- `_compute_quality`: if no `quality.md` → `(None, [])`. Else: `htext = harness_text(str(ev), repo_root, read_root)`; `prog = [{"dim":"no_overfit","score": no_overfit_score(htext, cases)}]`; `llm_dims = [d for d in (judge_quality(...) or []) if d["dim"] != "no_overfit"]`; `all_dims = prog + llm_dims`; return `(quality_mean(all_dims), all_dims)`.

---

## Task 1: `quality_prog.no_overfit_score`

**Files:** Create `scripts/loop_iter/quality_prog.py`, Create `tests/test_quality_prog.py`

- [ ] **Step 1: Create `tests/test_quality_prog.py`:**

```python
from loop_iter.quality_prog import no_overfit_score

def test_no_hardcoding_scores_10():
    cases = [{"id": "c1", "query": "What is the capital of France?", "expected": "Paris"}]
    # harness has general rules, no "paris", no verbatim query
    assert no_overfit_score("Answer in one word, no punctuation.", cases) == 10.0

def test_expected_answer_in_harness_scores_low():
    cases = [{"id": "c1", "query": "capital of France?", "expected": "Paris"}]
    assert no_overfit_score("For France answer Paris.", cases) == 0.0  # "paris" present -> hardcoded

def test_query_verbatim_in_harness_detected():
    cases = [{"id": "c1", "query": "a distinctive long query here", "expected": None}]
    assert no_overfit_score("When asked: a distinctive long query here -> X", cases) == 0.0

def test_short_expected_below_threshold_not_flagged():
    # expected len < 3 is not distinctive enough to flag (avoid false positives on tiny tokens)
    cases = [{"id": "c1", "query": "hi", "expected": "hi"}]
    assert no_overfit_score("say hi", cases) == 10.0  # "hi" (len 2) below threshold

def test_partial_hardcoding_scales():
    cases = [{"id": "c1", "query": "q one here", "expected": "Paris"},
             {"id": "c2", "query": "q two here", "expected": "Tokyo"}]
    # only "paris" present (1 of 2 hardcoded) -> 10 * (1 - 1/2) = 5.0
    assert no_overfit_score("answer Paris generally", cases) == 5.0

def test_no_cases_scores_10():
    assert no_overfit_score("any harness", []) == 10.0

def test_case_insensitive():
    cases = [{"id": "c1", "query": "x", "expected": "PaRiS"}]
    assert no_overfit_score("the answer is paris", cases) == 0.0
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_quality_prog.py -q` → expect FAIL (module missing).

- [ ] **Step 3: Create `scripts/loop_iter/quality_prog.py`:**

```python
"""Programmatic (non-LLM) harness-quality checks. Reliable where the LLM quality-judge degrades."""
from __future__ import annotations


def no_overfit_score(harness_text: str, cases: list[dict]) -> float:
    """Detect whether the harness hardcodes eval-specific content. Returns 0-10 (10 = none detected).

    A case counts as hardcoded if its `expected` answer (len >= 3) OR a distinctive substring of its
    `query` (len >= 8) appears verbatim (case-insensitive) in the harness. The expected-answer case is
    the classic overfit (the maker wrote the answer into the instructions); a verbatim query means the
    maker tailored the harness to that exact eval case. Short tokens (< 3 / < 8 chars) are skipped to
    avoid false positives. Score = 10 * (1 - hardcoded / len(cases)); 10.0 when no cases."""
    text = (harness_text or "").lower()
    if not cases:
        return 10.0
    hardcoded = 0
    for c in cases:
        hit = False
        exp = c.get("expected")
        if isinstance(exp, str) and len(exp) >= 3 and exp.lower() in text:
            hit = True
        q = c.get("query")
        if isinstance(q, str) and len(q) >= 8 and q.lower() in text:
            hit = True
        if hit:
            hardcoded += 1
    return 10.0 * (1 - hardcoded / len(cases))
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_quality_prog.py -q` → all pass. `.venv/bin/pytest -q` → green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/quality_prog.py tests/test_quality_prog.py
git commit -m "feat: programmatic no_overfit_score (reliable overfit detection, no LLM)"
```

---

## Task 2: `_compute_quality` helper + integrate programmatic no_overfit

**Files:** Modify `scripts/loop_iter/cli.py`, Modify `tests/test_cli.py`

- [ ] **Step 1: Add new tests + update existing ones in `tests/test_cli.py`.**

First, ADD a test proving the guardrail stays active via programmatic no_overfit when the LLM degrades:

```python
def test_cli_quality_reliable_when_llm_degrades(tmp_path, monkeypatch):
    """Programmatic no_overfit gives a quality signal even when the LLM quality-judge degrades to None
    (the maas flaky-judge scenario). Baseline with no hardcoding -> quality 10.0 despite LLM None."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)   # CLAUDE.md = "baseline" (no eval answer hardcoded)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("harness: [CLAUDE.md]\nthreshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"a distinctive long query here","expected":"PARIS"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("rubric: clarity")
    rp = RunPaths(base=str(repo), run_id="r1")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda *a, **k: None)   # LLM degraded
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    assert load_state(rp)["baseline_quality"] == 10.0   # programmatic no_overfit alone, LLM None
    import json
    dims = json.loads(rp.baseline_file.read_text())["quality_dims"]
    assert any(d["dim"] == "no_overfit" and d["score"] == 10.0 for d in dims)


def test_cli_quality_drops_when_harness_hardcodes_answer(tmp_path, monkeypatch):
    """If the harness hardcodes the eval answer, no_overfit drops -> quality lowers (guardrail signal)."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("For the capital question, answer Paris.")  # hardcodes "Paris"
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, env=env, check=True)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("harness: [CLAUDE.md]\nthreshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"capital of France","expected":"Paris"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("rubric: clarity")
    rp = RunPaths(base=str(repo), run_id="r1")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda *a, **k: None)   # LLM degraded
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    assert load_state(rp)["baseline_quality"] == 0.0   # no_overfit=0 (hardcoded), LLM None
```

Then UPDATE the two existing quality tests (Task-2/Task-3) for the combined dims. The cases in those tests use `{"query":"hi","expected":"hi"}` (both below thresholds) so `no_overfit=10.0`; combined with the stubbed LLM `clarity` dim:

- In `test_cli_baseline_computes_quality_when_quality_md_present`: stub returns `[{"dim":"clarity","score":8.0}]`. New quality = mean(10.0, 8.0) = **9.0**; quality_dims has 2 entries. Change the assertions `== 8.0` → `== 9.0`.
- In `test_cli_case_run_writes_quality_when_quality_md_present`: stub returns `[{"dim":"clarity","score":7.0}]`. New quality = mean(10.0, 7.0) = **8.5**. Change `q["quality"] == 7.0` → `== 8.5` and `load_scores(...)["quality"] == 7.0` → `== 8.5`. Keep the `VARIANT-HARNESS-CONTENT` captured-text assertions unchanged.

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (quality values changed).

- [ ] **Step 3: Add `_compute_quality` helper to `scripts/loop_iter/cli.py`** (place before `_baseline`):

```python
def _compute_quality(ev, repo_root: str, read_root: str, cases: list, llm_call):
    """Harness quality (opt-in via quality.md): programmatic no_overfit (reliable) + LLM dims per
    the rubric (degradable). The programmatic no_overfit overrides any LLM no_overfit dim. Returns
    (quality_mean_or_None, dims_list). No quality.md -> (None, []). When the LLM degrades, no_overfit
    alone still yields a non-None quality so the guardrail can fire on hardcoded-answer regressions."""
    from loop_iter.judge import judge_quality, quality_mean
    from loop_iter.adapter_generic import harness_text
    from loop_iter.quality_prog import no_overfit_score
    quality_md_path = ev / "quality.md"
    if not quality_md_path.exists():
        return None, []
    htext = harness_text(str(ev), repo_root, read_root)
    prog = [{"dim": "no_overfit", "score": no_overfit_score(htext, cases)}]
    llm_dims = [d for d in (judge_quality(htext, quality_md_path.read_text(), llm_call) or [])
                if d.get("dim") != "no_overfit"]
    all_dims = prog + llm_dims
    return quality_mean(all_dims), all_dims
```

- [ ] **Step 4: Rewire `_baseline`** to use the helper. Replace the existing quality block (the `quality_md_path = ev / "quality.md"` if/else that sets `out["quality"]`/`out["quality_dims"]`) with:

```python
    out["quality"], out["quality_dims"] = _compute_quality(ev, args.base, args.base, cases, llm_call)
```

(Keep the `rp.baseline_file.write_text(...)`, `advance_phase(..., updates={..., "baseline_quality": out["quality"]})`, and print exactly as-is. Remove the now-redundant `from loop_iter.judge import ...` / `from loop_iter.adapter_generic import harness_text` lines that were inside the old block — they're now in the helper. Keep `resolve_harness, build_run_case` imports that `_baseline` still uses.)

- [ ] **Step 5: Rewire `_case_run`** to use the helper. Replace the existing quality block (the `quality_md_path = ev / "quality.md"` if/else that sets `out["quality"]`/`out["quality_dims"]` and writes `quality.json`) with:

```python
    out["quality"], out["quality_dims"] = _compute_quality(ev, args.base, args.worktree, cases, llm_call)
    if rp.state_file.exists():
        (rp.run_dir / "quality.json").write_text(
            json.dumps({"round": args.round, "quality": out["quality"],
                        "quality_dims": out["quality_dims"]}, indent=2, ensure_ascii=False))
```

Then ensure the existing `if rp.state_file.exists(): append_round(rp, out); advance_phase(...)` / `else: append_round(rp, out)` structure still follows (append_round exactly once per path). `out["quality"]` is now always set (None when no quality.md) by the helper, so the `else: out["quality"] = None` line is removed.

- [ ] **Step 6:** `.venv/bin/pytest tests/test_cli.py -q` → all pass. `.venv/bin/pytest -q` → full green (111 = 109 + 2 new). Confirm `test_e2e_state_machine_full_flow` (no quality.md) still green.

- [ ] **Step 7: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: programmatic no_overfit in quality (reliable when LLM judge degrades)"
```

---

## Task 3: docs note

**Files:** `examples/toy/.self-iterate/toy-basic/quality.md`, `skills/self-iterate/SKILL.md`

- [ ] **Step 1:** In `examples/toy/.self-iterate/toy-basic/quality.md`, replace the `no_overfit` bullet with a note that it's auto-detected:

```markdown
- **no_overfit** (0-10): AUTO-DETECTED programmatically (not LLM-scored). 10 = no eval-specific content
  (expected answers or verbatim queries) found in the harness; 0 = the harness hardcodes eval answers.
  Reliable even when the LLM judge is unavailable.
```

- [ ] **Step 2:** In `skills/self-iterate/SKILL.md`, append to the quality note (the one added in Plan 2 Task 5): `The \`no_overfit\` dimension is detected programmatically (hardcoded-answer check), so it stays reliable even when the LLM quality-judge degrades.`

- [ ] **Step 3:** `.venv/bin/pytest -q` green (docs only).

- [ ] **Step 4: Commit:**
```bash
git add examples/toy/.self-iterate/toy-basic/quality.md skills/self-iterate/SKILL.md
git commit -m "docs: note no_overfit is programmatic/auto-detected"
```

---

## Self-Review

**1. Coverage:** programmatic no_overfit → Task 1. integration (helper + baseline + case-run) → Task 2. docs → Task 3. The reliable-when-degraded scenario (the dogfood gap) is locked by `test_cli_quality_reliable_when_llm_degrades` + `test_cli_quality_drops_when_harness_hardcodes_answer`. ✓

**2. Placeholders:** none; full code in every step.

**3. Consistency:** `no_overfit_score(harness_text, cases) -> float` consistent across Task 1 (def + tests) and Task 2 (`_compute_quality` call). `_compute_quality(ev, repo_root, read_root, cases, llm_call) -> (float|None, list)` consistent (def + baseline call with read_root=args.base + case-run call with read_root=args.worktree). The override `[d for d in llm_dims if d.get("dim") != "no_overfit"]` ensures no double-count. Existing tests updated to combined mean (9.0 / 8.5) computed from no_overfit=10 (cases use short "hi" below thresholds) + stubbed clarity. e2e (no quality.md) untouched → helper returns (None, []) → baseline_quality None → guardrail inactive. ✓
