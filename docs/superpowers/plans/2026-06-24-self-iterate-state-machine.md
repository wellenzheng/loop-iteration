# self-iterate state-machine core loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the external `ralph`/`autopilot` heartbeat with a built-in, on-disk state machine that drives the self-iterate loop with cli-enforced phase ordering, an explicit baseline step, a `max_rounds` cap, and a static diff+report — all under `.self-iterate/runs/<run_id>/`.

**Architecture:** `state.py` gains `state.json` primitives (init/load/write/advance) and `RunPaths` moves to `.self-iterate/runs/<run_id>/`. The cli grows `init`, `baseline`, `report` subcommands and **dual-mode phase guards** on `snapshot`/`case-run`/`goal-check`: when a `state.json` exists (inside an active run) the cli enforces + advances the phase; without one, the existing standalone behavior is unchanged (so current tests stay green). `goal-check` advances `goalcheck → done` (met or `max_rounds` hit) or `goalcheck → maker + round++`. The skill is rewritten from "one round only" to "read state.json, execute the current phase, advance, repeat until done".

**Tech Stack:** Python 3.11+, pytest, stdlib `json`/`pathlib`/`difflib`/`datetime`/`argparse`.

**Spec:** [docs/superpowers/specs/2026-06-24-self-iterate-setup-and-loop-design.md](../specs/2026-06-24-self-iterate-setup-and-loop-design.md) — covers §3.2 (state machine), §3.3 (cli invariants), §3.4 (baseline), §3.6 (path migration), §3.7 static-archive half of report. Quality guardrail (§3.5), dashboard (§3.7 live half), and the `setup` skill (§3.1) are **deferred to later plans**.

---

## File Structure

```
scripts/loop_iter/state.py        MODIFY — run_dir -> .self-iterate/runs/; add state_file/baseline_file/
                                            report_md/winner_diff props; init_state/load_state/write_state/
                                            advance_phase/_now
scripts/loop_iter/goal_check.py   MODIFY — add check_and_advance (goalcheck -> done|maker+round++)
scripts/loop_iter/cli.py          MODIFY — add init/baseline/report subcommands; dual-mode phase guards
                                            on snapshot (maker->eval) / case-run (eval->goalcheck) /
                                            goal-check (goalcheck->done|maker); add --run-id to snapshot
tests/test_state.py               APPEND — state.json primitives + run_dir path
tests/test_goal_check.py          APPEND — check_and_advance transitions + max_rounds cap
tests/test_cli.py                 APPEND — init/baseline/report + dual-mode phase guards
skills/self-iterate/SKILL.md      MODIFY — rewrite to state-machine loop
commands/self-iterate.md          MODIFY — start/setup subcommands
```

**Signatures:**
- `state.py`: `init_state(rp, goal: str, max_rounds: int) -> dict`; `load_state(rp) -> dict` (raises if absent); `write_state(rp, st) -> None` (atomic); `advance_phase(rp, expected: str, next_phase: str, updates: dict|None=None) -> dict`; `_now() -> str`.
- `state.py` `RunPaths` new props: `state_file`, `baseline_file`, `report_md`, `winner_diff`.
- `goal_check.py`: `check_and_advance(rp, goal_path: str, best_gate_rates: dict|None) -> dict`.
- `cli.py` new subcommands: `init --goal --eval --run-id [--base]`, `baseline --eval --run-id [--base]`, `report --eval --run-id [--base]`. `snapshot` gains optional `--run-id`.

**Phase values:** `baseline | maker | eval | goalcheck | done`. (`init` is a cli command that writes `state.json` with `phase=baseline`; it is not a phase value.)

---

## Task 1: `state.py` — path migration + `state.json` primitives

**Files:**
- Modify: `scripts/loop_iter/state.py`
- Test: `tests/test_state.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_state.py`:**

```python
import json, pytest
from loop_iter.state import (RunPaths, init_state, load_state, write_state, advance_phase)

def test_run_dir_under_self_iterate_runs(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    assert rp.run_dir == tmp_path / ".self-iterate" / "runs" / "r1"
    assert rp.state_file == rp.run_dir / "state.json"
    assert rp.baseline_file == rp.run_dir / "baseline.json"
    assert rp.report_md == rp.run_dir / "report.md"
    assert rp.winner_diff == rp.run_dir / "winner.diff"

def test_init_state_writes_baseline_phase(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    st = init_state(rp, "mygoal", 5)
    assert st["phase"] == "baseline"
    assert st["round"] == 0
    assert st["max_rounds"] == 5
    assert st["met"] is False
    assert st["goal"] == "mygoal"
    assert load_state(rp) == st

def test_load_state_raises_when_absent(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    with pytest.raises(FileNotFoundError):
        load_state(rp)

def test_advance_phase_checks_expected_and_advances(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    init_state(rp, "g", 3)
    st = advance_phase(rp, "baseline", "maker", updates={"round": 1})
    assert st["phase"] == "maker"
    assert st["round"] == 1
    assert load_state(rp)["phase"] == "maker"

def test_advance_phase_refuses_wrong_expected(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1")
    init_state(rp, "g", 3)
    with pytest.raises(RuntimeError, match="phase guard"):
        advance_phase(rp, "eval", "goalcheck")   # state is baseline, not eval
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_state.py -q` → expect FAIL (`ImportError: cannot import name init_state`).

- [ ] **Step 3: Rewrite `scripts/loop_iter/state.py`** (keep existing `RunPaths` props `scores`/`progress`/`variants_dir` and `write_scores`/`load_scores`/`append_round`/`write_progress`; change `run_dir`; add the new pieces):

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

@dataclass
class RunPaths:
    base: str
    run_id: str

    @property
    def run_dir(self) -> Path:
        return Path(self.base, ".self-iterate", "runs", self.run_id)

    def _ensure(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir

    @property
    def state_file(self) -> Path:
        return self._ensure() / "state.json"

    @property
    def baseline_file(self) -> Path:
        return self._ensure() / "baseline.json"

    @property
    def report_md(self) -> Path:
        return self._ensure() / "report.md"

    @property
    def winner_diff(self) -> Path:
        return self._ensure() / "winner.diff"

    @property
    def scores(self) -> Path:
        return self._ensure() / "scores.json"

    @property
    def progress(self) -> Path:
        return self._ensure() / "progress.md"

    @property
    def variants_dir(self) -> Path:
        d = self._ensure() / "variants"; d.mkdir(parents=True, exist_ok=True)
        return d


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---- scores.json (accumulating rounds) ----
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


# ---- state.json (phase machine) ----
def write_state(rp: RunPaths, st: dict) -> None:
    p = rp.state_file
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, indent=2, ensure_ascii=False))
    tmp.replace(p)

def load_state(rp: RunPaths) -> dict:
    if not rp.state_file.exists():
        raise FileNotFoundError(f"no state.json at {rp.state_file}")
    return json.loads(rp.state_file.read_text())

def init_state(rp: RunPaths, goal: str, max_rounds: int) -> dict:
    st = {"goal": goal, "run_id": rp.run_id, "round": 0, "max_rounds": max_rounds,
          "phase": "baseline", "met": False, "baseline_composite": None,
          "baseline_quality": None,
          "best": {"round": None, "composite": None, "worktree": None},
          "started_at": _now(), "updated_at": _now()}
    write_state(rp, st)
    return st

def advance_phase(rp: RunPaths, expected: str, next_phase: str,
                  updates: dict | None = None) -> dict:
    st = load_state(rp)
    if st["phase"] != expected:
        raise RuntimeError(f"phase guard: expected {expected!r}, state has {st['phase']!r}")
    st["phase"] = next_phase
    if updates:
        st.update(updates)
    st["updated_at"] = _now()
    write_state(rp, st)
    return st
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_state.py -q` → all pass. Then `.venv/bin/pytest -q` → full suite green (the path move doesn't break `test_run_paths_layout` because it only asserts the run_id dir name, not `.loop`).

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/state.py tests/test_state.py
git commit -m "feat: state.py moves to .self-iterate/runs + state.json phase machine"
```

---

## Task 2: cli `init` + `baseline` subcommands

**Files:**
- Modify: `scripts/loop_iter/cli.py` (add `_init`, `_baseline`, subparsers)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`:**

```python
def test_cli_init_writes_state_baseline(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 4\nweights: {gates: 1.0}\nregression: block\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    st = load_state(RunPaths(base=str(repo), run_id="r1"))
    assert st["phase"] == "baseline"
    assert st["max_rounds"] == 4
    assert json.loads(buf.getvalue())["phase"] == "baseline"


def test_cli_baseline_runs_cases_and_advances_to_maker(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("score len")
    # init first
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    # stub run_cases so we don't need a real agent/llm
    captured = {}
    def fake_run_cases(cases, worktree, gates_path, judge_md, weights, run_case_fn, judge_case_fn=None, llm_call=None):
        captured["called"] = True
        return {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}}
    monkeypatch.setattr("loop_iter.cli.run_cases", fake_run_cases, raising=False)
    # cli imports run_cases lazily inside _baseline via `from loop_iter.case_runner import run_cases`;
    # patch the source module so the lazy import picks up the stub:
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", fake_run_cases)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    assert captured["called"]
    st = load_state(RunPaths(base=str(repo), run_id="r1"))
    assert st["phase"] == "maker"
    assert st["round"] == 1
    assert st["baseline_composite"] == 0.5
    rp = RunPaths(base=str(repo), run_id="r1")
    assert json.loads(rp.baseline_file.read_text())["composite"] == 0.5


def test_cli_baseline_refuses_wrong_phase(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text("[]")
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    rp = RunPaths(base=str(repo), run_id="r1")
    init_state(rp, "g", 3)
    advance_to = rp  # force phase out of baseline
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "maker"; stmod.write_state(rp, st)
    try:
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "should refuse"
    except SystemExit as e:
        assert "phase guard" in str(e)
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (`init`/`baseline` subcommands unknown).

- [ ] **Step 3: Add `_init` and `_baseline` to `scripts/loop_iter/cli.py`** (place after `_setup`):

```python
def _init(args):
    import yaml
    from loop_iter.state import RunPaths, init_state
    goal_path = Path(args.eval, "goal.yaml")
    spec = yaml.safe_load(goal_path.read_text())
    rp = RunPaths(base=args.base, run_id=args.run_id)
    st = init_state(rp, args.goal, spec["max_rounds"])
    print(json.dumps({"run_id": args.run_id, "phase": st["phase"], "max_rounds": st["max_rounds"]}))


def _baseline(args):
    import yaml
    from loop_iter.state import RunPaths, load_state, advance_phase
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import resolve_harness, build_run_case
    from loop_iter.llm_client import chat as llm_call
    rp = RunPaths(base=args.base, run_id=args.run_id)
    st = load_state(rp)
    if st["phase"] != "baseline":
        raise SystemExit(f"phase guard: baseline requires phase=baseline, got {st['phase']}")
    ev = Path(args.eval)
    goal = yaml.safe_load((ev / "goal.yaml").read_text())
    cases = json.loads((ev / "cases.json").read_text())
    harness = resolve_harness(args.eval, args.base)
    rc = build_run_case(args.eval, goal.get("agent", {}), harness)
    out = run_cases(cases, args.base, str(ev / "gates.py"),
                    (ev / "judge.md").read_text(), goal["weights"],
                    run_case_fn=rc, llm_call=llm_call)
    rp.baseline_file.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    advance_phase(rp, "baseline", "maker",
                  updates={"round": 1, "baseline_composite": out["composite"]})
    print(json.dumps({"baseline_composite": out["composite"], "phase": "maker", "round": 1}))
```

- [ ] **Step 4: Register the subparsers in `main()`.** After the `setup` subparser block, add:

```python
    s = sub.add_parser("init")
    s.add_argument("--goal", required=True)
    s.add_argument("--eval", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--base", default=".")
    s.set_defaults(func=_init)

    s = sub.add_parser("baseline")
    s.add_argument("--eval", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--base", default=".")
    s.set_defaults(func=_baseline)
```

- [ ] **Step 5:** `.venv/bin/pytest tests/test_cli.py -q` → the 3 new tests pass. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 6: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: cli init + baseline subcommands (state-machine entry)"
```

---

## Task 3: dual-mode phase guards on `snapshot` (maker→eval) and `case-run` (eval→goalcheck)

**Files:**
- Modify: `scripts/loop_iter/cli.py` (`_snapshot`, `_case_run` + `snapshot` subparser gains `--run-id`)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`:**

```python
def test_cli_snapshot_advances_maker_to_eval_inside_run(tmp_path):
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    from loop_iter.state import RunPaths, init_state, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = load_state(rp); st["phase"] = "maker"; st["round"] = 1; stmod.write_state(rp, st)
    # stage a worktree + edit harness
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    wt = json.loads(buf.getvalue())["worktree"]
    Path(wt, "CLAUDE.md").write_text("edited")
    dest = str(rp.variants_dir / "round_1")
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        main(["snapshot", "--eval", str(ev), "--worktree", wt, "--dest", dest,
              "--base", str(repo), "--run-id", "r1"])
    assert load_state(rp)["phase"] == "eval"
    remove_worktree(wt)


def test_cli_snapshot_legacy_without_run_id_unchanged(tmp_path):
    # no state.json, no --run-id -> behaves as before, no phase advance
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    wt = json.loads(buf.getvalue())["worktree"]
    Path(wt, "CLAUDE.md").write_text("edited")
    dest = tmp_path / "snap"
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        main(["snapshot", "--eval", str(ev), "--worktree", wt, "--dest", str(dest), "--base", str(repo)])
    assert (dest / "CLAUDE.md").read_text() == "edited"   # snapshot still worked
    remove_worktree(wt)


def test_cli_case_run_advances_eval_to_goalcheck_inside_run(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    for ph, nxt in [("baseline", "maker")]:
        st = load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo),
              "--run-id", "r1", "--base", str(repo), "--round", 1])
    assert load_state(rp)["phase"] == "goalcheck"
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (snapshot doesn't advance; `--run-id` unknown on snapshot).

- [ ] **Step 3: Replace `_snapshot` in `scripts/loop_iter/cli.py`:**

```python
def _snapshot(args):
    from loop_iter.adapter_generic import resolve_harness, snapshot_harness
    harness = resolve_harness(args.eval, args.base)
    snapshot_harness(args.worktree, harness, args.dest)
    if args.run_id:
        from loop_iter.state import RunPaths, load_state, advance_phase
        rp = RunPaths(base=args.base, run_id=args.run_id)
        if rp.state_file.exists():
            st = load_state(rp)
            if st["phase"] != "maker":
                raise SystemExit(f"phase guard: snapshot requires phase=maker, got {st['phase']}")
            advance_phase(rp, "maker", "eval")
    print(json.dumps({"dest": args.dest, "files": harness}))
```

- [ ] **Step 4: Add `--run-id` to the `snapshot` subparser** (optional, default `None`). Change the snapshot subparser block to:

```python
    s = sub.add_parser("snapshot")
    s.add_argument("--eval", required=True)
    s.add_argument("--worktree", required=True)
    s.add_argument("--dest", required=True)
    s.add_argument("--base", default=".")
    s.add_argument("--run-id", default=None)
    s.set_defaults(func=_snapshot)
```

- [ ] **Step 5: Add the eval→goalcheck advance to `_case_run`.** In `scripts/loop_iter/cli.py`, find `_case_run` and after the `append_round(rp, out)` line, add (before the `print`):

```python
    # state-machine: advance eval -> goalcheck (only inside an active run)
    if rp.state_file.exists():
        from loop_iter.state import load_state, advance_phase
        st = load_state(rp)
        if st["phase"] != "eval":
            raise SystemExit(f"phase guard: case-run requires phase=eval, got {st['phase']}")
        advance_phase(rp, "eval", "goalcheck")
```

(`rp` is already constructed earlier in `_case_run` as `RunPaths(base=args.base, run_id=args.run_id)`.)

- [ ] **Step 6:** `.venv/bin/pytest tests/test_cli.py -q` → the 3 new tests pass. Then `.venv/bin/pytest -q` → full suite green (legacy snapshot test still passes via the no-`--run-id` path).

- [ ] **Step 7: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: dual-mode phase guards on snapshot (maker->eval) + case-run (eval->goalcheck)"
```

---

## Task 4: `goal_check.check_and_advance` — goalcheck→done | goalcheck→maker+round++

**Files:**
- Modify: `scripts/loop_iter/goal_check.py` (add `check_and_advance`)
- Modify: `scripts/loop_iter/cli.py` (`_goal_check` dual-mode)
- Test: `tests/test_goal_check.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_goal_check.py`:**

```python
import json
from loop_iter.state import RunPaths, init_state, write_state, load_state, append_round
from loop_iter.goal_check import check_and_advance

def _goal_yaml(tmp_path, threshold=0.8, max_rounds=3):
    p = tmp_path / "goal.yaml"
    p.write_text(f"threshold: {threshold}\nmax_rounds: {max_rounds}\nweights: {{gates: 1.0}}\nregression: block\n")
    return str(p)

def test_check_and_advance_met_goes_done(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1})
    append_round(rp, {"round": 1, "composite": 0.9, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path), None)
    assert v["met"] is True
    assert load_state(rp)["phase"] == "done"
    assert load_state(rp)["met"] is True

def test_check_and_advance_not_met_under_cap_loops_to_maker(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 1})
    append_round(rp, {"round": 1, "composite": 0.5, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path), None)
    assert v["met"] is False
    st = load_state(rp)
    assert st["phase"] == "maker"
    assert st["round"] == 2          # incremented for the next round

def test_check_and_advance_not_met_at_cap_goes_done(tmp_path):
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    write_state(rp, {**load_state(rp), "phase": "goalcheck", "round": 3})   # at cap
    append_round(rp, {"round": 3, "composite": 0.5, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    v = check_and_advance(rp, _goal_yaml(tmp_path), None)
    assert v["met"] is False
    st = load_state(rp)
    assert st["phase"] == "done"     # capped, not met -> done
    assert st["round"] == 3          # NOT incremented past cap

def test_check_and_advance_refuses_wrong_phase(tmp_path):
    import pytest
    rp = RunPaths(base=str(tmp_path), run_id="r1"); init_state(rp, "g", 3)
    # phase is still baseline
    with pytest.raises(RuntimeError, match="phase guard"):
        check_and_advance(rp, _goal_yaml(tmp_path), None)
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_goal_check.py -q` → expect FAIL (`ImportError: cannot import name check_and_advance`).

- [ ] **Step 3: Add `check_and_advance` to `scripts/loop_iter/goal_check.py`** (append after `check_latest`; import `load_state`/`write_state`/`_now` from state):

```python
from loop_iter.state import load_state, write_state, _now

def check_and_advance(rp: RunPaths, goal_path: str, best_gate_rates: dict | None) -> dict:
    """State-machine goal-check: compute verdict, then advance phase.
    met -> done (met=true); not met & round < max_rounds -> maker + round++;
    not met & round >= max_rounds -> done (met=false). Refuses if phase != goalcheck."""
    goal = yaml.safe_load(open(goal_path))
    st = load_state(rp)
    if st["phase"] != "goalcheck":
        raise RuntimeError(f"phase guard: goalcheck requires phase=goalcheck, got {st['phase']!r}")
    v = check_latest(rp, goal_path, best_gate_rates)
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
    v["phase"] = st["phase"]
    return v
```

- [ ] **Step 4: Make `_goal_check` in `scripts/loop_iter/cli.py` dual-mode.** Replace the body of `_goal_check` with:

```python
def _goal_check(args):
    from loop_iter.state import RunPaths
    from loop_iter.goal_check import check_latest, check_and_advance
    rp = RunPaths(base=args.base, run_id=args.run_id)
    best = json.loads(args.best_gate_rates) if args.best_gate_rates else None
    goal_path = str(Path(args.eval, "goal.yaml"))
    if rp.state_file.exists():
        v = check_and_advance(rp, goal_path, best)
    else:
        v = check_latest(rp, goal_path, best)
    print(json.dumps(v, indent=2))
    raise SystemExit(0 if v["met"] else 1)
```

- [ ] **Step 5:** `.venv/bin/pytest tests/test_goal_check.py -q` → all pass. Then `.venv/bin/pytest -q` → full suite green (the legacy `test_cli_goal_check_no_rounds_exits_1` has no `state.json`, so it takes the `check_latest` branch and still exits 1).

- [ ] **Step 6: Commit:**
```bash
git add scripts/loop_iter/goal_check.py scripts/loop_iter/cli.py tests/test_goal_check.py
git commit -m "feat: goal_check.check_and_advance drives goalcheck -> done | maker+round++"
```

---

## Task 5: cli `report` — `winner.diff` + `report.md`

**Files:**
- Modify: `scripts/loop_iter/cli.py` (add `_report`, subparser)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`:**

```python
def test_cli_report_writes_diff_and_md(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)   # repo has CLAUDE.md = "baseline"
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    append_round(rp, {"round": 1, "composite": 0.9, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    # snapshot an edited variant so the diff has something to show
    snap = rp.variants_dir / "round_1" / "CLAUDE.md"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text("round1-edited")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["report", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    diff = rp.winner_diff.read_text()
    assert "baseline/CLAUDE.md" in diff and "round_1/CLAUDE.md" in diff
    assert "-baseline" in diff and "+round1-edited" in diff
    md = rp.report_md.read_text()
    assert "best round: 1" in md
    assert "composite 0.900" in md

def test_cli_report_refuses_no_rounds(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    try:
        main(["report", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "should refuse"
    except SystemExit as e:
        assert "no rounds" in str(e)
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (`report` subcommand unknown).

- [ ] **Step 3: Add `_report` to `scripts/loop_iter/cli.py`** (place after `_baseline`):

```python
def _report(args):
    import difflib
    from loop_iter.state import RunPaths, load_state, load_scores
    from loop_iter.adapter_generic import resolve_harness
    rp = RunPaths(base=args.base, run_id=args.run_id)
    st = load_state(rp)
    data = load_scores(rp)
    rounds = data.get("rounds", [])
    if not rounds:
        raise SystemExit("report: no rounds recorded")
    best_round = data.get("best_round") or rounds[-1]["round"]
    best = next(r for r in rounds if r["round"] == best_round)
    snap_dir = rp.variants_dir / f"round_{best_round}"
    harness = resolve_harness(args.eval, args.base)
    diff_lines: list[str] = []
    for rel in harness:
        base_path = Path(args.base, rel)
        snap_path = snap_dir / rel
        base_lines = base_path.read_text().splitlines(keepends=True) if base_path.exists() else []
        snap_lines = snap_path.read_text().splitlines(keepends=True) if snap_path.exists() else []
        diff_lines.extend(difflib.unified_diff(
            base_lines, snap_lines,
            fromfile=f"baseline/{rel}", tofile=f"round_{best_round}/{rel}"))
    rp.winner_diff.write_text("".join(diff_lines))
    lines = [f"# Run {rp.run_id}", "",
             f"- met: {st['met']}", f"- best round: {best_round}",
             f"- best composite: {best['composite']:.3f}",
             f"- baseline composite: {st.get('baseline_composite')}", "", "## Per-round", ""]
    for r in rounds:
        lines.append(f"- round {r['round']}: composite {r['composite']:.3f}, "
                     f"gates {r.get('gate_pass_rates', {})}")
    rp.report_md.write_text("\n".join(lines) + "\n")
    print(json.dumps({"winner_diff": str(rp.winner_diff), "report_md": str(rp.report_md),
                      "best_round": best_round, "met": st["met"]}))
```

- [ ] **Step 4: Register the `report` subparser in `main()`** (after the `baseline` subparser):

```python
    s = sub.add_parser("report")
    s.add_argument("--eval", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--base", default=".")
    s.set_defaults(func=_report)
```

- [ ] **Step 5:** `.venv/bin/pytest tests/test_cli.py -q` → the 2 new tests pass. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 6: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: cli report subcommand (winner.diff + report.md via difflib)"
```

---

## Task 6: rewrite skill + command to the state-machine loop

**Files:**
- Modify: `skills/self-iterate/SKILL.md`
- Modify: `commands/self-iterate.md`

- [ ] **Step 1: Replace the body of `skills/self-iterate/SKILL.md`** (keep the frontmatter `name`/`description`; update the description to mention the built-in loop) with:

```markdown
# self-iterate (state-machine loop)

You drive the built-in self-iteration loop in the user's current repo (cwd), advancing an on-disk
state machine at `.self-iterate/runs/<run_id>/state.json`. The cli enforces phase ordering — you
cannot skip steps. You loop until `phase == done`.

## Inputs
- `goal` — eval name under `.self-iterate/` in cwd.
- `run_id` — a fresh id for this run (e.g. `YYYYMMDD_HHMMSS_shorttag`).

## Interpreter
```
PY=$(cat .self-iterate/.python 2>/dev/null || echo python)
```
Use `"$PY"` for every cli call below. `<plugin>` = this plugin's root.

## Loop
1. **Init** (once): `"$PY" <plugin>/scripts/loop_iter/cli.py init --goal <goal> --eval .self-iterate/<goal> --run-id <run_id>`. Creates `state.json` at `phase=baseline`.
2. **Baseline** (once): `"$PY" <plugin>/scripts/loop_iter/cli.py baseline --eval .self-iterate/<goal> --run-id <run_id>`. Scores the unmodified harness, writes `baseline.json`, advances to `phase=maker`, `round=1`.
3. **Per round, while `phase != done`:**
   a. **Stage + maker.** `apply-variant` for a worktree, then dispatch the `harness-rewriter` agent on the worktree (round 1: "cold start — sharpen the baseline harness to satisfy the gates"; later rounds: pass the failing gates + weak dims from the previous `case-run`).
   b. **Snapshot + advance.** `"$PY" <plugin>/scripts/loop_iter/cli.py snapshot --eval .self-iterate/<goal> --worktree <worktree> --dest .self-iterate/runs/<run_id>/variants/round_<N> --run-id <run_id>`. Snapshots the variant and advances `maker -> eval`.
   c. **Eval + advance.** `"$PY" <plugin>/scripts/loop_iter/cli.py case-run --eval .self-iterate/<goal> --worktree <worktree> --run-id <run_id> --round <N>`. Runs cases + judge, writes this round into `scores.json`, advances `eval -> goalcheck`.
   d. **Goal-check + advance.** `"$PY" <plugin>/scripts/loop_iter/cli.py goal-check --eval .self-iterate/<goal> --run-id <run_id>`. Computes the verdict and advances: `met` or `round >= max_rounds` -> `phase=done`; otherwise -> `phase=maker`, `round++`.
4. **Report** (at `done`): `"$PY" <plugin>/scripts/loop_iter/cli.py report --eval .self-iterate/<goal> --run-id <run_id>`. Writes `winner.diff` + `report.md`. Surface the best round + whether `met`.

## Resume
Re-invoking `start` reads `state.json` and resumes from the current phase. If you stall mid-round,
re-run `start` with the same `<run_id>` — the cli picks up at the recorded phase.

## Rules
- You advance phases only via the cli (each command checks + writes `state.json`). Never edit
  `state.json` by hand.
- Maker and checker are different agents; you are the orchestrator.
- The source repo is never mutated mid-loop — only the worktree. Merging the winner is the human's call.
- Stop only when `phase == done`. The cli enforces the `max_rounds` cap; you cannot loop past it.
```

- [ ] **Step 2: Replace the body of `commands/self-iterate.md`** (keep frontmatter `description`) with:

```markdown
# /self-iterate

Usage:
- `/self-iterate setup` — interactive: reads the repo, proposes the eval spec, confirms with you,
  writes `.self-iterate/<goal>/`, then resolves the Python env (`agent.venv` or bootstrap) to
  `.self-iterate/.python`. (The interactive proposer is a separate skill; until it lands, hand-write
  the spec from `examples/toy/.self-iterate/toy-basic/`.)
- `/self-iterate start <goal>` — runs the built-in state-machine loop to completion (baseline →
  maker/checker rounds → goal-check → report), persisting everything under
  `.self-iterate/runs/<run_id>/`. `/self-iterate toward <goal>` is an alias.
- `/self-iterate setup` (env only) is still run once automatically before `start` if `.self-iterate/.python`
  is missing.

## What `start` does
Dispatches the `self-iterate` skill, which loops by advancing an on-disk state machine
(`.self-iterate/runs/<run_id>/state.json`). The cli enforces phase ordering and the `max_rounds` cap
(from `goal.yaml`), so the loop runs until the goal is met or the cap is hit — no external
ralph/autopilot needed. The loop never auto-merges; `report` writes `winner.diff` + `report.md` and
you decide whether to merge the winning worktree.

## Before first use
Create `.self-iterate/<goal>/` with `goal.yaml`, `cases.json`, `gates.py`, `judge.md`
(copy `examples/toy/.self-iterate/toy-basic/` as a template). For a non-Claude-CLI agent, add a
`run_case.py` escape hatch.
```

- [ ] **Step 3:** Verify both files start with `---` frontmatter and the cli paths are intact. No tests affected (skills/commands are not exercised by pytest).

- [ ] **Step 4: Commit:**
```bash
git add skills/self-iterate/SKILL.md commands/self-iterate.md
git commit -m "feat: rewrite self-iterate skill/command to built-in state-machine loop"
```

---

## Self-Review (completed during authoring)

**1. Spec coverage (for this plan's slice):**
- §3.2 state machine → Tasks 1 (primitives), 2 (init/baseline), 3 (snapshot/case-run guards), 4 (goal-check advance), 6 (skill loop). ✓
- §3.3 cli invariants (phase guards, max_rounds cap, no-false-met) → Task 4 (`check_and_advance` computes met from scores+goal; cap forces done). ✓
- §3.4 baseline step → Task 2 (`baseline`). ✓
- §3.6 path migration → Task 1 (`run_dir` → `.self-iterate/runs/`). ✓
- §3.7 static archive (winner.diff + report.md) → Task 5. ✓ (live dashboard half deferred.)
- Deferred to later plans (not this plan's scope): §3.5 quality guardrail, §3.7 live dashboard, §3.1 setup skill. ✓

**2. Placeholder scan:** No TBD/TODO. Every code step shows full code. Dual-mode guard logic is spelled out (check `state_file.exists()` / `args.run_id`). The skill's "round 1: cold start … later rounds: pass failing gates" mirrors the existing skill's prose pattern.

**3. Type consistency:** `init_state(rp, goal, max_rounds)`, `load_state(rp)` (raises), `write_state(rp, st)`, `advance_phase(rp, expected, next_phase, updates=None)` — used consistently in Tasks 1–4. `check_and_advance(rp, goal_path, best_gate_rates)` consistent in Task 4 (def + tests + cli call). `RunPaths` new props (`state_file`, `baseline_file`, `report_md`, `winner_diff`) used in Tasks 1/2/5. `--run-id` added to `snapshot` (Task 3) matches the test's `--run-id r1`. Phase values `baseline|maker|eval|goalcheck|done` consistent across all tasks. `_now` imported from `state` in Task 4's `goal_check.py` (defined in Task 1's `state.py`). `load_scores`/`append_round`/`best_round` reused unchanged. Legacy `check_latest` branch preserved so `test_cli_goal_check_no_rounds_exits_1` stays green.
