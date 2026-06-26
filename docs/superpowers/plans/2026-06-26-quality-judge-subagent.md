# quality-judge sub-agent + quality_target — Implementation Plan (5b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make harness-quality (规范度) an **auxiliary optimization target** (opt-in via `quality_target`): a `quality-judge` sub-agent scores the variant harness (clarity/maintainability) + produces actionable `maker_feedback`; the maker receives quality dims + feedback; `met` requires `quality ≥ quality_target`; case-evaluator ∥ quality-judge run in parallel. `no_overfit` stays programmatic (reliable floor). Default (no `quality_target`) = current guardrail behavior, unchanged.

**Architecture:** New `quality-judge` agent (reads variant harness + quality.md, returns `{dims, maker_feedback}`). New cli `quality-merge` merges the sub-agent's LLM dims (+ keeps programmatic `no_overfit`) into `quality.json`/`baseline.json` + the round's `quality` in scores.json — in two modes: `--baseline` (baseline phase) and `--round N` (eval phase). `case-run`/`baseline` compute ONLY `no_overfit` (skip in-process `judge_quality`) when `quality_target` is set — the sub-agent provides the LLM dims. `goal_check.check_and_advance` requires `quality ≥ quality_target` (on top of composite + no gate regression + no quality regression). The `self-iterate` skill dispatches case-evaluator ∥ quality-judge and (for baseline) baseline ∥ quality-judge, then `quality-merge`, then passes quality dims + `maker_feedback` to the maker. `no_overfit` (programmatic) is always the reliable floor; the sub-agent's LLM dims degrade gracefully (merge keeps no_overfit if the sub-agent fails).

**Tech Stack:** Python 3.11+, pytest.

**Spec basis:** [local-service + quality-judge spec](2026-06-25-local-service-and-quality-judge-design.md) §4 (Q1-Q5).

**Parallelism note:** case-evaluator (output) and quality-judge (harness) are independent per round → dispatched concurrently. The sub-agent reads the harness (not cases, not no_overfit — no_overfit is programmatic and merge keeps it), so it needs no result from case-run → true parallel.

---

## File Structure

```
scripts/loop_iter/cli.py            MODIFY — quality-merge subcommand; _compute_quality skip_llm; case-run+baseline pass skip_llm when quality_target set
scripts/loop_iter/goal_check.py     MODIFY — check_and_advance: met requires quality ≥ quality_target
scripts/loop_iter/validate_spec.py  MODIFY — quality_target optional number; warn if set without quality.md
agents/quality-judge.md             CREATE — the quality-judge sub-agent
skills/self-iterate/SKILL.md        MODIFY — quality_target mode: parallel dispatch + quality-merge + maker feedback + two-phase
skills/self-iterate-setup/SKILL.md  MODIFY — ask quality_target in the rubric step
tests/test_cli.py                   APPEND — quality-merge (both modes), case-run/baseline skip_llm
tests/test_goal_check.py            APPEND — quality_target met requirement
tests/test_validate_spec.py         APPEND — quality_target checks
tests/test_quality_target_integration.py  CREATE — stubbed quality-judge → quality-merge → goal_check flow
```

**Signatures:**
- `cli.quality-merge --eval <goal> --run-id <id> [--base .] (--baseline | --round <N>) --from <quality_judge.json>` — merges the sub-agent's `{dims, maker_feedback}` (LLM dims, excluding `no_overfit`) with the programmatic `no_overfit` already in quality.json/baseline.json; recomputes `quality = mean(all_dims)`; writes back + updates scores.json round quality (or state.baseline_quality for --baseline).
- `_compute_quality(ev, repo_root, read_root, cases, llm_call, skip_llm=False)` — `skip_llm=True` → only `no_overfit` (no `judge_quality` call).
- `quality-judge` agent → `{"dims": [{"dim": "clarity", "score": 8.0}, ...], "maker_feedback": "<actionable suggestions>"}`.

**quality_judge.json** (written by the skill from the sub-agent's return, at `.self-iterate/runs/<id>/quality_judge.json` for rounds, or `quality_judge_baseline.json` for baseline): `{"dims": [...], "maker_feedback": "..."}`.

---

## Task 1: `quality-merge` cli subcommand

**Files:** Modify `scripts/loop_iter/cli.py`, Test `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`:**

```python
def test_cli_quality_merge_round(tmp_path):
    """quality-merge --round N merges sub-agent LLM dims + no_overfit, updates quality.json +
    the round's quality in scores.json."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nquality_target: 8.0\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("clarity / maintainability")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    # case-run wrote provisional quality.json (no_overfit only) + a round with provisional quality
    (rp.run_dir / "quality.json").write_text('{"round": 1, "quality": 10.0, "quality_dims": [{"dim": "no_overfit", "score": 10.0}]}')
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 10.0, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    # sub-agent output (LLM dims + feedback)
    judge_path = rp.run_dir / "quality_judge.json"
    judge_path.write_text('{"dims": [{"dim": "clarity", "score": 6.0}, {"dim": "maintainability", "score": 6.0}], "maker_feedback": "trim section 3"}')
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "r1", "--base", str(repo),
              "--round", "1", "--from", str(judge_path)])
    # merged: no_overfit(10) + clarity(6) + maintainability(6) = mean 7.333
    import json
    from loop_iter.state import load_scores
    q = json.loads((rp.run_dir / "quality.json").read_text())
    assert abs(q["quality"] - (10 + 6 + 6) / 3) < 1e-6
    assert q["maker_feedback"] == "trim section 3"
    assert any(d["dim"] == "no_overfit" and d["score"] == 10.0 for d in q["quality_dims"])
    assert load_scores(rp)["rounds"][-1]["quality"] == q["quality"]


def test_cli_quality_merge_baseline(tmp_path):
    """quality-merge --baseline merges into baseline.json + state.baseline_quality."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nquality_target: 8.0\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    # baseline wrote provisional baseline.json (no_overfit only) + state.baseline_quality
    rp.baseline_file.write_text('{"composite": 0.5, "quality": 10.0, "quality_dims": [{"dim":"no_overfit","score":10.0}]}')
    st = load_state(rp); st["baseline_quality"] = 10.0; from loop_iter.state import write_state; write_state(rp, st)
    judge_path = rp.run_dir / "quality_judge_baseline.json"
    judge_path.write_text('{"dims": [{"dim": "clarity", "score": 9.0}], "maker_feedback": ""}')
    import io, contextlib, json
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "r1", "--base", str(repo),
              "--baseline", "--from", str(judge_path)])
    b = json.loads(rp.baseline_file.read_text())
    assert abs(b["quality"] - (10 + 9) / 2) < 1e-6
    assert load_state(rp)["baseline_quality"] == b["quality"]


def test_cli_quality_merge_overrides_subagent_no_overfit(tmp_path):
    """If the sub-agent (wrongly) returns a no_overfit dim, the programmatic value wins."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    (rp.run_dir / "quality.json").write_text('{"round": 1, "quality": 10.0, "quality_dims": [{"dim": "no_overfit", "score": 10.0}]}')
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 10.0, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    judge_path = rp.run_dir / "quality_judge.json"
    # sub-agent returns a (wrong) no_overfit=2.0 + clarity=8.0 -> programmatic no_overfit(10) wins
    judge_path.write_text('{"dims": [{"dim": "no_overfit", "score": 2.0}, {"dim": "clarity", "score": 8.0}], "maker_feedback": ""}')
    import io, contextlib, json
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "r1", "--base", str(repo),
              "--round", "1", "--from", str(judge_path)])
    q = json.loads((rp.run_dir / "quality.json").read_text())
    no_overfit = [d for d in q["quality_dims"] if d["dim"] == "no_overfit"][0]
    assert no_overfit["score"] == 10.0   # programmatic, not the sub-agent's 2.0
    assert len(q["quality_dims"]) == 2   # no_overfit + clarity only (no dup)
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (`quality-merge` unknown).

- [ ] **Step 3: Add `_quality_merge` to `scripts/loop_iter/cli.py`** (after `_smoke`):

```python
def _quality_merge(args):
    import json
    from loop_iter.state import RunPaths, load_state, write_state, load_scores, write_scores
    from loop_iter.judge import quality_mean
    rp = RunPaths(base=args.base, run_id=args.run_id)
    judge = json.loads(Path(args.from).read_text())
    llm_dims = [d for d in (judge.get("dims") or []) if d.get("dim") != "no_overfit"]
    feedback = judge.get("maker_feedback")

    def merge(existing: dict) -> tuple[float, list]:
        no_overfit = [d for d in existing.get("quality_dims", []) if d.get("dim") == "no_overfit"]
        all_dims = no_overfit + llm_dims
        return quality_mean(all_dims), all_dims

    if args.baseline:
        b = json.loads(rp.baseline_file.read_text())
        b["quality"], b["quality_dims"] = merge(b)
        b["maker_feedback"] = feedback
        rp.baseline_file.write_text(json.dumps(b, indent=2, ensure_ascii=False))
        st = load_state(rp); st["baseline_quality"] = b["quality"]; write_state(rp, st)
        print(json.dumps({"baseline_quality": b["quality"]}))
    else:
        qpath = rp.run_dir / "quality.json"
        q = json.loads(qpath.read_text())
        q["quality"], q["quality_dims"] = merge(q)
        q["maker_feedback"] = feedback
        qpath.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        data = load_scores(rp)
        for r in data["rounds"]:
            if r["round"] == args.round:
                r["quality"] = q["quality"]; r["quality_dims"] = q["quality_dims"]
                r["maker_feedback"] = feedback
        write_scores(rp, data)
        print(json.dumps({"round": args.round, "quality": q["quality"]}))
```

And register the subparser in `main()` (after `smoke`):

```python
    s = sub.add_parser("quality-merge")
    s.add_argument("--eval", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--base", default=".")
    s.add_argument("--from", required=True, help="path to quality-judge JSON {dims, maker_feedback}")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--baseline", action="store_true")
    g.add_argument("--round", type=int)
    s.set_defaults(func=_quality_merge)
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_cli.py -q` → the 3 new tests pass. `.venv/bin/pytest -q` → full green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: quality-merge cli (merge quality-judge dims + no_overfit, baseline/round modes)"
```

---

## Task 2: `goal_check` quality_target requirement

**Files:** Modify `scripts/loop_iter/goal_check.py`, Test `tests/test_goal_check.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_goal_check.py`:**

```python
def test_check_and_advance_quality_target_blocks_met_when_below(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1, "baseline_quality": 9.0})
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 7.0, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    # quality_target 8.0 -> quality 7.0 < 8.0 -> met blocked (composite 0.9 >= 0.8 though)
    v = check_and_advance(rp, _goal_yaml(tmp_path, threshold=0.8, max_rounds=3), None)
    # _goal_yaml doesn't set quality_target; write a goal with it
    import yaml
    gp = tmp_path / "goal.yaml"
    gp.write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nquality_target: 8.0\n")
    v = check_and_advance(rp, str(gp), None)
    assert v["met"] is False
    assert "quality" in v["reason"].lower() and "target" in v["reason"].lower()
    assert load_state(rp)["phase"] == "maker" and load_state(rp)["round"] == 2


def test_check_and_advance_quality_target_met_when_at_or_above(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1, "baseline_quality": 9.0})
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 8.5, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    gp = tmp_path / "goal.yaml"
    gp.write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nquality_target: 8.0\n")
    v = check_and_advance(rp, str(gp), None)
    assert v["met"] is True
    assert load_state(rp)["phase"] == "done"


def test_check_and_advance_no_quality_target_unaffected(tmp_path):
    """Without quality_target, met is governed by composite + regression (current behavior)."""
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1, "baseline_quality": 9.0})
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 3.0, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    # no quality_target; quality 3.0 vs baseline 9.0 -> regression (blocks met) regardless
    v = check_and_advance(rp, _goal_yaml(tmp_path, threshold=0.8, max_rounds=3), None)
    assert v["met"] is False   # quality regression (Plan 2), not quality_target
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_goal_check.py -q` → expect FAIL.

- [ ] **Step 3: Add quality_target to `check_and_advance`** in `scripts/loop_iter/goal_check.py`. Read the current `check_and_advance`. After the existing quality-regression guardrail block (which forces met False on `latest_q < bq - tol`), add the quality_target check. The guardrail block currently looks like:

```python
    if bq is not None and latest_q is not None and latest_q < bq - tol:
        if v["met"]:
            v["met"] = False
            v["reason"] = (f"quality regression: {latest_q:.2f} < baseline {bq:.2f} - tol {tol}")
```

Add after it (still using `v` from `check_latest`, before the phase transition):

```python
    # quality_target: an absolute floor on quality (opt-in). When set, met requires quality >= target.
    qt = goal.get("quality_target")
    if qt is not None and latest_q is not None and latest_q < qt:
        if v["met"]:
            v["met"] = False
            v["reason"] = (f"quality below target: {latest_q:.2f} < quality_target {qt}")
```

(Place this right after the regression guardrail, before `# phase transition`. `goal` is already loaded at the top of check_and_advance. Keep everything else unchanged.)

- [ ] **Step 4:** `.venv/bin/pytest tests/test_goal_check.py -q` → all pass. `.venv/bin/pytest -q` → full green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/goal_check.py tests/test_goal_check.py
git commit -m "feat: goal_check requires quality >= quality_target (opt-in absolute floor)"
```

---

## Task 3: `case-run` + `baseline` skip in-process judge_quality when quality_target set

**Files:** Modify `scripts/loop_iter/cli.py` (`_compute_quality`, `_case_run`, `_baseline`), Test `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`:**

```python
def test_cli_case_run_skips_llm_quality_when_quality_target_set(tmp_path, monkeypatch):
    """When quality_target is set, case-run computes only no_overfit (no judge_quality call) — the
    sub-agent will provide LLM dims via quality-merge."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state, load_scores
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nquality_target: 8.0\nharness: [CLAUDE.md]\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    def boom(*a, **k):
        raise AssertionError("judge_quality must NOT be called when quality_target set")
    monkeypatch.setattr(jm, "judge_quality", boom)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo), "--run-id", "r1", "--base", str(repo), "--round", "1"])
    # provisional quality = no_overfit only (10.0, since harness "baseline" has no eval answers)
    assert load_scores(rp)["rounds"][-1]["quality"] == 10.0
    dims = load_scores(rp)["rounds"][-1]["quality_dims"]
    assert [d["dim"] for d in dims] == ["no_overfit"]


def test_cli_case_run_keeps_llm_quality_when_no_quality_target(tmp_path, monkeypatch):
    """Without quality_target, case-run calls judge_quality as today (current behavior)."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_scores
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nharness: [CLAUDE.md]\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda *a, **k: [{"dim": "clarity", "score": 7.0}])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo), "--run-id", "r1", "--base", str(repo), "--round", "1"])
    dims = load_scores(rp)["rounds"][-1]["quality_dims"]
    assert {"dim": "clarity", "score": 7.0} in dims   # judge_quality was called
    assert any(d["dim"] == "no_overfit" for d in dims)
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (case-run calls judge_quality regardless).

- [ ] **Step 3: Add `skip_llm` to `_compute_quality` and wire `case-run`/`baseline`.** In `scripts/loop_iter/cli.py`:

(a) `_compute_quality` — add `skip_llm=False` param; when True, skip `judge_quality`:
```python
def _compute_quality(ev, repo_root: str, read_root: str, cases: list, llm_call, skip_llm: bool = False):
    """... (existing docstring) ..."""
    from loop_iter.judge import judge_quality, quality_mean
    from loop_iter.adapter_generic import harness_text
    from loop_iter.quality_prog import no_overfit_score
    quality_md_path = ev / "quality.md"
    if not quality_md_path.exists():
        return None, []
    htext = harness_text(str(ev), repo_root, read_root)
    prog = [{"dim": "no_overfit", "score": no_overfit_score(htext, cases)}]
    if skip_llm:
        llm_dims = []
    else:
        llm_dims = [d for d in (judge_quality(htext, quality_md_path.read_text(), llm_call) or [])
                    if d.get("dim") != "no_overfit"]
    all_dims = prog + llm_dims
    return quality_mean(all_dims), all_dims
```

(b) `_case_run` — read `quality_target` from goal; pass `skip_llm`:
```python
    out["quality"], out["quality_dims"] = _compute_quality(
        ev, args.base, args.worktree, cases, llm_call, skip_llm=bool(goal.get("quality_target")))
```
(`goal` is already loaded in `_case_run`.)

(c) `_baseline` — same:
```python
    out["quality"], out["quality_dims"] = _compute_quality(
        ev, args.base, args.base, cases, llm_call, skip_llm=bool(goal.get("quality_target")))
```
(`goal` is already loaded in `_baseline`.)

- [ ] **Step 4:** `.venv/bin/pytest tests/test_cli.py -q` → the 2 new tests pass. `.venv/bin/pytest -q` → full green (existing tests have no quality_target → skip_llm False → unchanged).

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: case-run/baseline skip in-process judge_quality when quality_target set (sub-agent provides LLM dims)"
```

---

## Task 4: `quality-judge` agent

**Files:** Create `agents/quality-judge.md`

- [ ] **Step 1: Create `agents/quality-judge.md`:**

````markdown
---
name: quality-judge
description: The harness-quality CHECKER in the self-iteration loop (only when the goal sets `quality_target`). Given a worktree holding a candidate harness + the quality.md rubric, read the harness files and score the LLM dimensions (clarity, maintainability — NOT no_overfit, which is auto-detected), plus produce specific, actionable `maker_feedback` (trim/dedupe/place). Return strict JSON {dims, maker_feedback}. You do NOT run cases or score outputs — that's case-evaluator's job.
---

You are the quality-judge. You score the agent's HARNESS FILES (the prompt/skills/instructions the
maker wrote) — NOT the agent's outputs. You run only when the goal sets `quality_target`.

## Inputs
- worktree (your CWD for reading): the variant harness to score.
- harness files (relative to worktree): the files to read + judge.
- quality.md rubric path: the dims to score (clarity, maintainability, ...). NOTE: `no_overfit` is
  AUTO-DETECTED programmatically — do NOT score it; score only the other dims in the rubric.

## Your job
Read the harness files. For each LLM dim in the rubric EXCEPT no_overfit, score 0-10:
- **clarity**: 10 = unambiguous, well-structured, model-followable; 0 = vague/contradictory.
- **maintainability**: 10 = concise, readable, easy to edit; 0 = bloated/repetitive/brittle.
(Other dims per the rubric.)

Then write **maker_feedback**: 1-3 specific, actionable suggestions to improve the harness 规范度
(e.g. "section 3 'transfer rules' duplicates section 1 — merge them", "the intro is 200 words of
hedging — trim to 3 rules"). These go to the maker as the auxiliary optimization signal. Be
concrete and surgical — name the file/section + the change. Do NOT suggest changes that would hurt
task performance (gates must still pass); focus on clarity/maintainability/structure.

## Return
Return ONLY strict JSON (no prose outside it):
```json
{"dims": [{"dim": "clarity", "score": 8.0}, {"dim": "maintainability", "score": 7.0}],
 "maker_feedback": "<specific actionable suggestions, or empty string if the harness is already clean>"}
```

## Rules
- Score ONLY the harness files — never the agent's outputs.
- Do NOT score `no_overfit` (it's auto-detected; if you return one, it's ignored).
- maker_feedback must be actionable + specific (name file/section + change), not generic.
- Never hardcode eval-case content into suggestions.
- If a dim is genuinely not assessable from the harness, give it a mid score (5) and note why in
  maker_feedback.
````

- [ ] **Step 2:** No tests (agent doc). Run `.venv/bin/pytest -q` (confirm green).

- [ ] **Step 3: Commit:**
```bash
git add agents/quality-judge.md
git commit -m "feat: quality-judge agent (harness 规范度 checker + maker_feedback)"
```

---

## Task 5: skill docs — `quality_target` mode (parallel + merge + maker feedback) + setup asks it

**Files:** Modify `skills/self-iterate/SKILL.md`, Modify `skills/self-iterate-setup/SKILL.md`, Modify `scripts/loop_iter/validate_spec.py` (+ test)

- [ ] **Step 1: `skills/self-iterate/SKILL.md`** — add the `quality_target` mode. Read the current skill. In the Loop section, after the eval step (case-run), add a note describing the quality_target path. Insert after the baseline step:

```markdown
   *(If goal.yaml sets `quality_target`, quality becomes an auxiliary optimization target: the
   maker also drives harness 规范度 toward the target. In the baseline phase AND each eval phase,
   dispatch the `quality-judge` agent IN PARALLEL with case-evaluation — case-evaluator runs cases
   (output), quality-judge reads the variant harness (clarity/maintainability + maker_feedback);
   they're independent. case-run/baseline compute only the programmatic `no_overfit` when
   `quality_target` is set; the sub-agent provides the LLM dims. After both return: write the
   quality-judge's JSON to `.self-iterate/runs/<run_id>/quality_judge.json` (or
   `quality_judge_baseline.json` for baseline), then run:
   `quality-merge --eval ... --run-id ... --baseline --from quality_judge_baseline.json` (baseline)
   or `--round <N> --from quality_judge.json` (eval) — it merges the sub-agent's LLM dims with the
   programmatic no_overfit into quality.json/baseline.json + the round's quality. Then goal-check
   (met now requires quality ≥ quality_target). For the maker next round, pass the failing gates +
   weak output-judge dims + the quality-judge's `maker_feedback` + weak quality dims — two-phase:
   gates first, then harness 规范度. No `quality_target` → current behavior, no quality-judge.)*
```

And in the maker step (3a), append: when `quality_target` is set, also pass the previous round's
`maker_feedback` + weak quality dims (read from `.self-iterate/runs/<run_id>/quality.json`).

- [ ] **Step 2: `skills/self-iterate-setup/SKILL.md`** — in step 4 (Ask the eval criteria), after proposing gates + judge, add: ask whether to set `quality_target` (opt-in auxiliary target on harness 规范度; if yes, add `quality_target: <float>` to goal.yaml — recommend 8.0). Update the goal.yaml template in Required files to mention `quality_target` is optional.

- [ ] **Step 3: `scripts/loop_iter/validate_spec.py`** — optional `quality_target` check: if set, must be a number (0-10); warn if set but no quality.md. Add to the goal-checks block:

```python
            qt = goal.get("quality_target")
            if qt is not None:
                if not isinstance(qt, (int, float)) or isinstance(qt, bool):
                    problems.append("goal.yaml: quality_target must be a number (0-10)")
                if not (d / "quality.md").exists():
                    warnings.append("goal.yaml: quality_target set but no quality.md — quality-judge has no rubric")
```

Append a test to `tests/test_validate_spec.py`:
```python
def test_quality_target_must_be_number(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    goal = (d / "goal.yaml").read_text() + "quality_target: high\n"
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("quality_target" in p for p in v["problems"])
```

- [ ] **Step 4:** `.venv/bin/pytest -q` → green. Commit:
```bash
git add skills/self-iterate/SKILL.md skills/self-iterate-setup/SKILL.md scripts/loop_iter/validate_spec.py tests/test_validate_spec.py
git commit -m "feat: quality_target mode in skills (parallel quality-judge + merge + maker feedback) + validate"
```

---

## Task 6: integration test (stubbed quality-judge → quality-merge → goal_check)

**Files:** Create `tests/test_quality_target_integration.py`

- [ ] **Step 1: Create `tests/test_quality_target_integration.py`:**

```python
"""End-to-end (cli-level) of the quality_target flow with a STUBBED quality-judge: case-run computes
no_overfit only -> quality-merge merges a stubbed sub-agent's LLM dims -> goal-check requires
quality >= quality_target. Validates the wiring (the quality-judge agent itself is LLM behavior,
covered by dogfooding)."""
import json
from loop_iter.cli import main
from loop_iter.state import RunPaths, init_state, load_state, load_scores


def test_quality_target_flow_case_run_merge_goal_check(tmp_path, monkeypatch):
    import io, contextlib, subprocess
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("baseline harness")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, env=env, check=True)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text(
        "threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n"
        "quality_target: 8.0\nharness: [CLAUDE.md]\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q","expected":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    (ev / "quality.md").write_text("clarity / maintainability")
    rp = RunPaths(base=str(repo), run_id="qt")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "qt", "--base", str(repo)])
    # baseline: no_overfit only (skip_llm), provisional baseline_quality
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda *a, **k:
        [{"dim": "clarity", "score": 9.0}])  # would be called only if NOT skipping; baseline skips
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "qt", "--base", str(repo)])
    # baseline_quality provisional = no_overfit only (10.0)
    assert load_state(rp)["baseline_quality"] == 10.0
    # stubbed quality-judge on baseline -> merge
    jp = rp.run_dir / "quality_judge_baseline.json"
    jp.write_text('{"dims": [{"dim": "clarity", "score": 9.0}, {"dim": "maintainability", "score": 9.0}], "maker_feedback": ""}')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "qt", "--base", str(repo),
              "--baseline", "--from", str(jp)])
    # baseline_quality = mean(no_overfit=10, clarity=9, maintainability=9) = 9.333
    assert abs(load_state(rp)["baseline_quality"] - (10 + 9 + 9) / 3) < 1e-6

    # set up round 1 at eval phase
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo), "--run-id", "qt", "--base", str(repo), "--round", "1"])
    # provisional round quality = no_overfit only (10.0)
    assert load_scores(rp)["rounds"][-1]["quality"] == 10.0
    # stubbed quality-judge on the variant -> merge (low quality: clarity 5, maintainability 5)
    jp2 = rp.run_dir / "quality_judge.json"
    jp2.write_text('{"dims": [{"dim": "clarity", "score": 5.0}, {"dim": "maintainability", "score": 5.0}], "maker_feedback": "trim section 2"}')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "qt", "--base", str(repo),
              "--round", "1", "--from", str(jp2)])
    # round quality = mean(10, 5, 5) = 6.667 < quality_target 8.0 -> met blocked -> loops
    assert abs(load_scores(rp)["rounds"][-1]["quality"] - (10 + 5 + 5) / 3) < 1e-6
    import pytest
    with pytest.raises(SystemExit) as ei:
        main(["goal-check", "--eval", str(ev), "--run-id", "qt", "--base", str(repo)])
    assert ei.value.code == 1   # not met (quality 6.667 < target 8.0)
    st = load_state(rp)
    assert st["phase"] == "maker" and st["round"] == 2   # loops
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_quality_target_integration.py -q` → should PASS (Tasks 1-3 wired it). Debug if needed.

- [ ] **Step 3: Commit:**
```bash
git add tests/test_quality_target_integration.py
git commit -m "test: quality_target flow (stubbed quality-judge -> merge -> goal_check)"
```

---

## Self-Review (completed during authoring)

**1. Spec coverage (§4 / Q1-Q5):**
- Q1 quality-judge sub-agent → Task 4. ✓
- Q2 quality_target opt-in (met requires ≥ target; maker feedback; sub-agent dispatched) → Task 2 (goal_check) + Task 3 (skip_llm) + Task 5 (skill). ✓
- Q3 no_overfit programmatic floor (merge keeps it, overrides sub-agent) → Task 1 (merge override test). ✓
- Q4 parallel dispatch (case-evaluator ∥ quality-judge) → Task 5 (skill doc). ✓
- Q5 gaming mitigation (gates primary; quality_target only after gates; no_overfit catches overfit) → Task 5 (two-phase) + Task 2 (met still requires composite + no gate regression). ✓
- baseline parity (baseline also quality-judged + merged) → Task 1 (--baseline mode) + Task 5 (skill baseline ∥ quality-judge). ✓

**2. Placeholder scan:** No TBD/TODO. Full code in Tasks 1-3; Task 4/5 are docs with exact content; Task 6 is a complete integration test.

**3. Type consistency:** `quality-merge (--baseline | --round N) --from <file>` consistent (Task 1 def + tests + Task 5 skill calls + Task 6 integration). `_compute_quality(..., skip_llm=False)` consistent (Task 3 def + case-run/baseline calls). `quality_target` read in goal_check (Task 2), case-run/baseline (Task 3), validate_spec (Task 5). `quality_judge.json` / `quality_judge_baseline.json` paths consistent (Task 1 reads --from; Task 5 skill writes them; Task 6 stubs them). `quality-judge` agent return `{dims, maker_feedback}` consistent (Task 4 + Task 1 merge reads dims/maker_feedback). no_overfit override (drop sub-agent's no_overfit, keep programmatic) consistent (Task 1 merge + test). Default (no quality_target) → skip_llm False → current behavior → existing tests + e2e unchanged.

**Backward compat:** no `quality_target` → case-run/baseline call judge_quality (current), no quality-judge, no quality-merge, goal_check unchanged. All existing tests + e2e stay green.
