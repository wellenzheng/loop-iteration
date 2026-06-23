# Plugin-ization & Generic Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `loop-iteration` into a downloadable Claude Code plugin with a generic Claude-native adapter, so integrating users write only a `.self-iterate/<goal>/` eval spec — no adapter code.

**Architecture:** Repo becomes the plugin source (`.claude-plugin/` + root `skills/`/`agents/`/`commands/` + bundled `scripts/loop_iter/`). A new generic adapter (`resolve_harness` convention+override, `claude -p` default `run_case`, drop-in `run_case.py` escape hatch) replaces the toy-specific adapter. A unified `cli.py` exposes `apply-variant`/`case-run`/`goal-check`/`setup`. The toy becomes an `examples/` demo of the user-facing layout.

**Tech Stack:** Python 3.11+, pytest, PyYAML, httpx, git worktrees, Claude Code plugin layout (`.claude-plugin/plugin.json`).

**Spec:** [docs/superpowers/specs/2026-06-23-plugin-ization-design.md](../specs/2026-06-23-plugin-ization-design.md)

---

## File Structure (target)

```
loop-iteration/
├── .claude-plugin/plugin.json            NEW — {name, description, author}
├── skills/{loop-engineering,self-iterate,case-evaluator}/SKILL.md   MOVED from .claude/skills/ (self-iterate, case-evaluator UPDATED)
├── agents/{harness-rewriter,goal-checker}.md   MOVED from .claude/agents/ (harness-rewriter UPDATED)
├── commands/self-iterate.md              NEW — slash command
├── scripts/loop_iter/                    MOVED from src/loop_iter/
│   ├── scoring.py gates.py judge.py adapter.py state.py llm_client.py   (unchanged logic)
│   ├── adapter_generic.py                NEW — resolve_harness, load_run_case, run_case_default, build_agent_cmd, snapshot_harness
│   ├── case_runner.py                    UPDATED — run_case_fn(case, worktree); __main__ removed
│   ├── goal_check.py                     UPDATED — __main__ removed (functions kept)
│   └── cli.py                            NEW — unified CLI (apply-variant/case-run/goal-check/setup)
├── examples/toy/                         MOVED from adapters/toy + evals/toy-basic, restructured to user layout
│   ├── CLAUDE.md                           (toy agent harness — deliberately vague baseline)
│   └── .self-iterate/toy-basic/{goal.yaml,cases.json,gates.py,judge.md}
├── tests/                                UPDATED — test_run_case.py → folded into test_adapter_generic.py
├── pyproject.toml                        UPDATED — pythonpath/packages → scripts
├── README.md                             UPDATED — plugin readme
└── docs/  .loop/
```

**Key signatures (consistent across tasks):**
- `resolve_harness(eval_dir: str, repo_root: str) -> list[str]` — harness file paths relative to repo_root.
- `load_run_case(eval_dir: str) -> callable | None` — user `run_case(case, worktree, harness_paths)` if `run_case.py` present, else None.
- `run_case_default(case, worktree, config) -> Result` — `claude -p` invocation; `build_agent_cmd(config)` builds the command.
- `snapshot_harness(worktree: str, harness_paths: list[str], dest: str) -> None` — copy listed files preserving structure.
- `run_cases(...)` now calls `run_case_fn(case, worktree)` (3rd arg dropped; cli builds closures).

---

## Task 1: Move Python core src/loop_iter → scripts/loop_iter

**Files:**
- Move: `src/loop_iter/` → `scripts/loop_iter/`
- Modify: `pyproject.toml`

- [ ] **Step 1: Move the package**

```bash
cd /Users/zhengweijun/agent/loop-iteration
mkdir -p scripts
git mv src/loop_iter scripts/loop_iter
rmdir src 2>/dev/null || true
```

- [ ] **Step 2: Update `pyproject.toml`** — change `packages.find` where and pytest pythonpath from `src` to `scripts`:

```toml
[tool.setuptools.packages.find] = { where = ["scripts"] }

[tool.pytest.ini_options]
pythonpath = ["scripts", "."]
testpaths = ["tests"]
```

- [ ] **Step 3: Reinstall editable + run tests**

```bash
. .venv/bin/pip install -e . -q
.venv/bin/pytest -q
```
Expected: `30 passed`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: move loop_iter package from src/ to scripts/ (plugin bundling)"
```

---

## Task 2: Plugin manifest + move skills/agents to plugin root

**Files:**
- Create: `.claude-plugin/plugin.json`
- Move: `.claude/skills/` → `skills/`, `.claude/agents/` → `agents/`

- [ ] **Step 1: Create `.claude-plugin/plugin.json`**

```json
{
  "name": "self-iterate",
  "description": "A Claude-Code-native loop that self-iterates any agent's harness (prompt/skills/tools) until a user-defined, verifiable goal is met. Users provide only a .self-iterate/<goal>/ eval spec; a generic claude-p adapter covers Claude-native agents, with a drop-in run_case.py escape hatch for others.",
  "author": { "name": "loop-iteration" }
}
```

- [ ] **Step 2: Move skills and agents to plugin root**

```bash
cd /Users/zhengweijun/agent/loop-iteration
git mv .claude/skills skills
git mv .claude/agents agents
# remove .claude/ if now empty (leave it if it holds other state)
rmdir .claude 2>/dev/null || true
```

- [ ] **Step 3: Tests still green (moves don't affect Python tests)**

```bash
.venv/bin/pytest -q
```
Expected: `30 passed`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: add plugin manifest; move skills/agents to plugin root"
```

---

## Task 3: adapter_generic.resolve_harness (convention + override)

**Files:**
- Create: `scripts/loop_iter/adapter_generic.py`
- Test: `tests/test_adapter_generic.py`

- [ ] **Step 1: Write the failing tests `tests/test_adapter_generic.py`**

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_adapter_generic.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_iter.adapter_generic'`

- [ ] **Step 3: Write `scripts/loop_iter/adapter_generic.py`** (resolve_harness only for now)

```python
from __future__ import annotations
import yaml
from pathlib import Path

DEFAULT_HARNESS_GLOBS = [
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/skills/**/*.md",
    ".claude/agents/**/*.md",
]

def resolve_harness(eval_dir: str, repo_root: str) -> list[str]:
    """Harness file paths (relative to repo_root) to iterate. Default convention
    unless goal.yaml's `harness:` key overrides it. Absent paths are skipped."""
    goal_path = Path(eval_dir, "goal.yaml")
    spec = yaml.safe_load(goal_path.read_text()) if goal_path.exists() else {}
    patterns = spec.get("harness") or DEFAULT_HARNESS_GLOBS
    root = Path(repo_root)
    seen: set[str] = set()
    out: list[str] = []
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if rel not in seen:
                seen.add(rel); out.append(rel)
    return sorted(out)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_adapter_generic.py -q`
Expected: `3 passed`. Then `.venv/bin/pytest -q` → `33 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_iter/adapter_generic.py tests/test_adapter_generic.py
git commit -m "feat: add resolve_harness (default convention + goal.yaml override)"
```

---

## Task 4: adapter_generic — load_run_case, run_case_default, build_agent_cmd, snapshot_harness

**Files:**
- Modify: `scripts/loop_iter/adapter_generic.py`
- Test: `tests/test_adapter_generic.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_adapter_generic.py`**

```python
import importlib.util
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_adapter_generic.py -q`
Expected: FAIL — `ImportError: cannot import name load_run_case ...`

- [ ] **Step 3: Append to `scripts/loop_iter/adapter_generic.py`**

```python
import shutil
import subprocess
import importlib.util


def load_run_case(eval_dir: str):
    """Return the user's run_case(case, worktree, harness_paths) if eval_dir/run_case.py
    exists, else None (caller uses the claude-p default). Escape hatch for non-Claude agents."""
    p = Path(eval_dir, "run_case.py")
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_user_run_case_{p.stat().st_mtime_ns}", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    if not hasattr(mod, "run_case"):
        raise ValueError(f"{p} must define run_case(case, worktree, harness_paths)")
    return mod.run_case


def build_agent_cmd(config: dict) -> list[str]:
    """Build the claude CLI command from goal.yaml's `agent:` config."""
    cmd = ["claude", "-p", "--permission-mode", config.get("permission_mode", "bypassPermissions")]
    if config.get("model"):
        cmd += ["--model", config["model"]]
    cmd += list(config.get("extra_args", []))
    return cmd


def run_case_default(case: dict, worktree: str, config: dict) -> dict:
    """Run claude -p on the case in the worktree. Never raises (crash/timeout -> error field)."""
    try:
        proc = subprocess.run(
            build_agent_cmd(config), cwd=worktree, input=case.get("query", ""),
            capture_output=True, text=True, timeout=config.get("timeout", 120),
        )
        output = proc.stdout.strip()
        error = None if proc.returncode == 0 else f"exit {proc.returncode}: {proc.stderr.strip()[:300]}"
    except Exception as exc:
        output, error = "", f"run_case error: {exc!r}"
    return {"case_id": case["id"], "output": output, "trace": {}, "error": error}


def snapshot_harness(worktree: str, harness_paths: list[str], dest: str) -> None:
    """Copy each harness file from the worktree into dest, preserving relative structure."""
    wt = Path(worktree)
    for rel in harness_paths:
        src = wt / rel
        if not src.exists():
            continue
        out = Path(dest, rel)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_adapter_generic.py -q`
Expected: `8 passed`. Then `.venv/bin/pytest -q` → `38 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_iter/adapter_generic.py tests/test_adapter_generic.py
git commit -m "feat: add generic run_case (claude-p default + escape hatch) and snapshot_harness"
```

---

## Task 5: run_cases calls run_case_fn(case, worktree)

**Files:**
- Modify: `scripts/loop_iter/case_runner.py` (drop the 3rd `agent_subdir` arg from the run_case_fn call)
- Modify: `tests/test_case_runner.py` (update stubs)

- [ ] **Step 1: Update tests `tests/test_case_runner.py`** — stubs now take `(case, worktree)`:

```python
from loop_iter.case_runner import run_cases

def _stub_run_case(output_map):
    def rc(case, worktree):
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

def test_run_cases_computes_composite(tmp_path):
    cases = [{"id": "c1", "query": "q", "expected": None},
             {"id": "c2", "query": "q", "expected": None}]
    rc = _stub_run_case({"c1": "OK", "c2": "nope"})
    judge = lambda result, case, judge_md, llm_call: [{"dim": "tone", "score": 10.0}]
    out = run_cases(
        cases=cases, worktree="/tmp/ignored",
        gates_path=_gate_mod(tmp_path), judge_md="x",
        weights={"gates": 1.0, "tone": 1.0},
        run_case_fn=rc, judge_case_fn=judge, llm_call=None,
    )
    assert out["composite"] == 0.75
    assert out["gate_pass_rates"] == {"has_ok": 0.5}
    assert len(out["cases"]) == 2

def test_run_cases_falls_back_to_gates_only_when_judge_none(tmp_path):
    cases = [{"id": "c1", "query": "q", "expected": None}]
    rc = _stub_run_case({"c1": "OK"})
    judge = lambda *a, **k: None
    out = run_cases(
        cases=cases, worktree="/tmp/x",
        gates_path=_gate_mod(tmp_path), judge_md="x",
        weights={"gates": 1.0, "tone": 1.0},
        run_case_fn=rc, judge_case_fn=judge, llm_call=None,
    )
    assert out["composite"] == 1.0
    assert out["judge_means"] == {}
```

- [ ] **Step 2: Run to verify failure** (old impl still passes 3 args)

Run: `.venv/bin/pytest tests/test_case_runner.py -q`
Expected: FAIL — `TypeError: rc() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Update `scripts/loop_iter/case_runner.py`** — change `run_cases` signature and the call. Replace the existing `run_cases` function entirely with:

```python
from __future__ import annotations
from loop_iter.gates import load_gates, run_gates
from loop_iter.judge import judge_case as _default_judge
from loop_iter.scoring import composite, gate_pass_rates, judge_means

def run_cases(cases: list[dict], worktree: str,
              gates_path: str, judge_md: str, weights: dict[str, float],
              run_case_fn, judge_case_fn=_default_judge, llm_call=None) -> dict:
    """Run every case through run_case_fn(case, worktree), then gates + judge -> RunScores.

    judge_case_fn defaults to loop_iter.judge.judge_case; tests inject a stub.
    A None judge result for a case => no dims for that case (gates-only contribution).
    llm_call is forwarded to judge_case_fn (real judge uses it; stubs ignore it).
    """
    gates = load_gates(gates_path)
    case_scores: list[dict] = []
    for case in cases:
        result = run_case_fn(case, worktree)
        gate_results = run_gates(result, case, gates)
        judged = judge_case_fn(result, case, judge_md, llm_call)
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

(Also **delete** the `_cli()` function and its `if __name__ == "__main__"` block from `case_runner.py` — the unified CLI in Task 6 replaces it.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_case_runner.py -q`
Expected: `2 passed`. Then `.venv/bin/pytest -q` → full suite green (the deleted `_cli` was never tested).

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_iter/case_runner.py tests/test_case_runner.py
git commit -m "refactor: run_cases calls run_case_fn(case, worktree); drop case_runner CLI"
```

---

## Task 6: Unified cli.py (apply-variant / case-run / goal-check / setup)

**Files:**
- Create: `scripts/loop_iter/cli.py`
- Modify: `scripts/loop_iter/goal_check.py` (delete its `_cli` + `__main__`; keep `check_latest`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Strip the CLI from `scripts/loop_iter/goal_check.py`** — delete the `_cli()` function and the `if __name__ == "__main__": _cli()` block. Keep `check_latest` and its imports. The file becomes just:

```python
from __future__ import annotations
import yaml
from loop_iter.state import RunPaths, load_scores

def check_latest(rp: RunPaths, goal_path: str, best_gate_rates: dict | None) -> dict:
    """Read the latest round's stored composite + gate_pass_rates + goal -> GoalVerdict."""
    goal = yaml.safe_load(open(goal_path))
    data = load_scores(rp)
    if not data.get("rounds"):
        return {"met": False, "round": 0, "composite": 0.0,
                "gate_pass_rates": {}, "regressed_gates": [], "reason": "no rounds yet"}
    latest = data["rounds"][-1]
    gpr = latest.get("gate_pass_rates", {})
    comp = latest.get("composite", 0.0)
    best = best_gate_rates or {}
    regressed = [g for g, r in gpr.items() if g in best and r < best[g]]
    blocked = goal.get("regression", "block") == "block" and bool(regressed)
    within = latest["round"] <= goal["max_rounds"]
    met = (comp >= goal["threshold"]) and (not blocked) and within
    if not within:
        reason = f"hit max_rounds ({goal['max_rounds']})"
    elif blocked:
        reason = f"gate regression: {regressed}"
    elif comp < goal["threshold"]:
        reason = f"composite {comp:.3f} < threshold {goal['threshold']}"
    else:
        reason = "met"
    return {"met": met, "round": latest["round"], "composite": comp,
            "gate_pass_rates": gpr, "regressed_gates": regressed, "reason": reason}
```

- [ ] **Step 2: Write `scripts/loop_iter/cli.py`**

```python
"""Unified CLI for the self-iterate plugin: apply-variant | case-run | goal-check | setup.
Invoked by the skills as: python <plugin>/scripts/loop_iter/cli.py <cmd> ..."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path


def _apply_variant(args):
    from loop_iter.adapter import apply_variant
    from loop_iter.adapter_generic import resolve_harness
    wt = apply_variant(repo_root=args.base, baseline_ref=args.baseline, agent_subdir=".")
    harness = resolve_harness(args.eval, args.base)
    print(json.dumps({"worktree": wt, "harness": harness}))


def _case_run(args):
    import yaml
    from loop_iter.state import RunPaths, append_round
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import resolve_harness, load_run_case, run_case_default
    ev = Path(args.eval)
    goal = yaml.safe_load((ev / "goal.yaml").read_text())
    cases = json.loads((ev / "cases.json").read_text())
    harness = resolve_harness(args.eval, args.base)
    user_rc = load_run_case(args.eval)
    if user_rc is not None:
        rc = lambda case, worktree: user_rc(case, worktree, harness)
    else:
        cfg = goal.get("agent", {})
        rc = lambda case, worktree: run_case_default(case, worktree, cfg)
    from loop_iter.llm_client import chat as llm_call
    out = run_cases(cases, args.worktree, str(ev / "gates.py"),
                    (ev / "judge.md").read_text(), goal["weights"],
                    run_case_fn=rc, llm_call=llm_call)
    out["round"] = args.round
    rp = RunPaths(base=args.base, run_id=args.run_id)
    append_round(rp, out)
    print(json.dumps({"round": args.round, "composite": out["composite"],
                      "gate_pass_rates": out["gate_pass_rates"]}))


def _goal_check(args):
    from loop_iter.state import RunPaths
    from loop_iter.goal_check import check_latest
    rp = RunPaths(base=args.base, run_id=args.run_id)
    best = json.loads(args.best_gate_rates) if args.best_gate_rates else None
    v = check_latest(rp, str(Path(args.eval, "goal.yaml")), best)
    print(json.dumps(v, indent=2))
    raise SystemExit(0 if v["met"] else 1)


def _setup(args):
    """Bootstrap a venv at .self-iterate/.venv and install pyyaml + httpx (idempotent)."""
    venv = Path(args.base, ".self-iterate", ".venv")
    if not venv.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    pip = str(venv / "bin" / "pip")
    subprocess.run([pip, "install", "-q", "pyyaml", "httpx"], check=True)
    print(json.dumps({"venv": str(venv), "deps": ["pyyaml", "httpx"]}))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m loop_iter.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("apply-variant")
    s.add_argument("--eval", required=True)
    s.add_argument("--base", default=".")
    s.add_argument("--baseline", default="HEAD")
    s.set_defaults(func=_apply_variant)

    s = sub.add_parser("case-run")
    s.add_argument("--eval", required=True)
    s.add_argument("--worktree", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--base", default=".")
    s.add_argument("--round", type=int, required=True)
    s.set_defaults(func=_case_run)

    s = sub.add_parser("goal-check")
    s.add_argument("--eval", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--base", default=".")
    s.add_argument("--best-gate-rates", default=None)
    s.set_defaults(func=_goal_check)

    s = sub.add_parser("setup")
    s.add_argument("--base", default=".")
    s.set_defaults(func=_setup)

    a = ap.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Write failing tests `tests/test_cli.py`**

```python
import json, subprocess
from pathlib import Path


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("baseline")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, env=env, check=True)
    return repo


def test_cli_goal_check_no_rounds_exits_1(tmp_path):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (repo / ".loop").mkdir()
    try:
        main(["goal-check", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "should have exited 1"
    except SystemExit as e:
        assert e.code == 1


def test_cli_apply_variant_prints_worktree_and_harness(tmp_path):
    from loop_iter.cli import main
    import io, contextlib
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    data = json.loads(buf.getvalue())
    assert "worktree" in data and Path(data["worktree"]).exists()
    assert data["harness"] == ["CLAUDE.md"]
    # source untouched
    from loop_iter.adapter import remove_worktree
    remove_worktree(data["worktree"])
    assert (repo / "CLAUDE.md").read_text() == "baseline"
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_cli.py -q`
Expected: `2 passed`. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_iter/cli.py scripts/loop_iter/goal_check.py tests/test_cli.py
git commit -m "feat: add unified cli.py (apply-variant/case-run/goal-check/setup)"
```

---

## Task 7: Update skills + harness-rewriter for the generic adapter

**Files:**
- Modify: `skills/self-iterate/SKILL.md`
- Modify: `skills/case-evaluator/SKILL.md`
- Modify: `agents/harness-rewriter.md`

- [ ] **Step 1: Rewrite `skills/self-iterate/SKILL.md`**

```markdown
---
name: self-iterate
description: Drives ONE round of agent-harness self-iteration for the agent in the current repo. Read state → stage a candidate worktree → dispatch the harness-rewriter (maker) to fix last round's failures on the resolved harness paths → dispatch the case-evaluator (checker) to score it → snapshot + update state → report the goal-checker verdict. The loop is run-until-done (ralph/autopilot) wrapping this skill; goal-checker is the separate reviewer. Use when the user runs "/self-iterate toward <goal>" or says "self-iterate toward <goal>".
---

# self-iterate (one round)

You run exactly one round, in the user's current repo (cwd). The broader loop is driven by run-until-done — you do not loop yourself.

## Inputs
- `goal` — eval name under `.self-iterate/` in cwd.
- `run_id` — current run id. `round` — this round's number (1-based).

## One round
1. **Stage the variant.** Resolve a worktree + harness paths via the bundled CLI (path is relative to this plugin's root):
   ```
   python <plugin-root>/scripts/loop_iter/cli.py apply-variant --eval .self-iterate/<goal> --baseline HEAD
   ```
   Read the printed JSON: `{worktree, harness}`. `harness` is the list of files the maker may edit.
2. **Maker.** Dispatch the `harness-rewriter` agent with `worktree`, `harness` (the paths), and last round's findings (round 1: "cold start — sharpen the baseline harness to satisfy the gates"). It edits only files in `harness`.
3. **Checker.** Dispatch the `case-evaluator` skill on the worktree. It runs:
   ```
   python <plugin-root>/scripts/loop_iter/cli.py case-run --eval .self-iterate/<goal> --worktree <worktree> --run-id <run_id> --round <round>
   ```
   which writes this round's RunScores into `.loop/iterate/<run_id>/scores.json` and returns failing gates + weak dims.
4. **Snapshot + state.** Snapshot the variant's harness files into `.loop/iterate/<run_id>/variants/round_<N>/` (provenance). Append a one-line summary to `.loop/iterate/<run_id>/progress.md`.
5. **Stop-condition handoff.** Run the goal-checker:
   ```
   python <plugin-root>/scripts/loop_iter/cli.py goal-check --eval .self-iterate/<goal> --run-id <run_id> [--best-gate-rates '<json>']
   ```
   Exit 0 = met (stop, surface the best variant); exit 1 = not met (return findings; run-until-done fires the next round).

## Run-until-done
Wrap this skill in **ralph / autopilot**: worker = "run one self-iterate round toward `<goal>`", reviewer = the `goal-checker` agent. The stop condition (composite ≥ threshold, no gate regression, ≤ max_rounds) is judged by an agent that did NOT do the work.

## Rules
- One round only. Maker and checker are different agents; you are the orchestrator.
- State lives in the user's repo (`.loop/iterate/<run_id>/`). The plugin is stateless.
- Source repo is never mutated mid-loop — only the worktree. Merging the winner is the human's call.
```

- [ ] **Step 2: Rewrite `skills/case-evaluator/SKILL.md`**

```markdown
---
name: case-evaluator
description: The CHECKER stage of the self-iteration loop. Given a worktree holding a candidate harness and an eval spec under .self-iterate/<goal>/, run all cases (via the generic claude-p run_case, or the user's drop-in run_case.py escape hatch), score them with the gates + LLM-judge, write the round's RunScores to state, and return the failing gates + weak judge dims for the maker.
---

# case-evaluator (checker)

You evaluate one candidate harness variant and record the result. You do NOT rewrite anything.

## Inputs
- `worktree`, `eval` (`.self-iterate/<goal>`), `run_id`, `round`.

## Procedure
Run the deterministic evaluator (it runs cases, gates, judge; you do not eyeball):
```
python <plugin-root>/scripts/loop_iter/cli.py case-run \
  --eval <eval> --worktree <worktree> --run-id <run_id> --round <round>
```
This writes the round into `.loop/iterate/<run_id>/scores.json` and prints the composite + gate pass-rates.

## Return to the loop driver
- The composite score and each gate's pass-rate.
- The **failing gates** and **weak judge dims**, with one example case each — the `findings` the maker acts on. Group as themes where obvious.

## Rules
- A case that errored scores 0 on gates; flag it, don't abort the round.
- If the judge failed for a case (no dims), that case is gates-only this round.
- You record; goal-checker decides whether the goal is met.
```

- [ ] **Step 3: Update `agents/harness-rewriter.md`** — change the "Input" + "Hard rules" so the maker edits the resolved `harness` paths (not a fixed `agent_files/` subdir). Replace the `## Input (given to you)` and first hard-rule sections with:

```markdown
## Input (given to you)
- `worktree` — path to a git worktree of the user's repo.
- `harness` — the list of harness file paths (relative to the worktree root) you may edit, e.g. `["CLAUDE.md", ".claude/skills/foo/SKILL.md"]`.
- `findings` — the failing gates and weak judge dims from the last round, with per-case examples.

## How to rewrite (this is the whole job)
1. Read every file listed in `harness`.
2. From the findings, infer **themes** (e.g. "outputs are multi-word when one word is required", "hedges instead of answering"). Do NOT memorize individual cases.
3. Edit the harness files to encode the fix as a *general rule* the agent will follow on unseen cases.

## Hard rules
- **Themes, not per-case patches.** Encode the rule, never hard-code an answer.
- **You only edit files in `harness`.** Do not touch anything else.
- **You do not score or run cases.** The checker does that next.
```
(Keep the `---` frontmatter and the `# harness-rewriter (maker)` heading; only replace the Input/How-to/Hard-rules sections as shown.)

- [ ] **Step 4: Commit**

```bash
git add skills/self-iterate/SKILL.md skills/case-evaluator/SKILL.md agents/harness-rewriter.md
git commit -m "feat: update self-iterate/case-evaluator skills + maker for generic adapter"
```

---

## Task 8: Toy → examples/ (user-layout demo); remove adapters/ + evals/

**Files:**
- Create: `examples/toy/CLAUDE.md`
- Move: `evals/toy-basic/*` → `examples/toy/.self-iterate/toy-basic/`
- Delete: `adapters/` (run_case logic now in adapter_generic), `evals/`, `tests/test_run_case.py`

- [ ] **Step 1: Create the example toy repo layout**

```bash
cd /Users/zhengweijun/agent/loop-iteration
mkdir -p examples/toy/.self-iterate/toy-basic
git mv evals/toy-basic/goal.yaml examples/toy/.self-iterate/toy-basic/goal.yaml
git mv evals/toy-basic/cases.json examples/toy/.self-iterate/toy-basic/cases.json
git mv evals/toy-basic/gates.py   examples/toy/.self-iterate/toy-basic/gates.py
git mv evals/toy-basic/judge.md   examples/toy/.self-iterate/toy-basic/judge.md
rmdir evals/toy-basic evals 2>/dev/null || true
```

- [ ] **Step 2: Create `examples/toy/CLAUDE.md`** (the toy agent's deliberately-vague baseline harness — moved from the old `adapters/toy/agent_files/`)

```markdown
# Toy Answerer

When asked a question, respond helpfully. (Baseline is deliberately vague — the loop
should sharpen this into "answer in exactly one word, no punctuation".)
```

- [ ] **Step 3: Add an `agent:` block to `examples/toy/.self-iterate/toy-basic/goal.yaml`** so the example shows the optional override. The file should read:

```yaml
threshold: 0.85
max_rounds: 3
regression: block
weights:
  gates: 2.0
  conciseness: 1.0
agent:
  model: claude-haiku-4-5-20251001
  permission_mode: bypassPermissions
  timeout: 120
```

- [ ] **Step 4: Delete the old toy adapter + its test**

```bash
git rm -r adapters
git rm tests/test_run_case.py
```
(`adapters/toy/run_case.py` logic now lives in `adapter_generic.run_case_default`; `adapters/toy/apply_variant.py` is replaced by the generic `apply_variant` + `resolve_harness`.)

- [ ] **Step 5: Verify the example parses + full suite green**

```bash
.venv/bin/python -c "import yaml,json,importlib.util; yaml.safe_load(open('examples/toy/.self-iterate/toy-basic/goal.yaml')); json.load(open('examples/toy/.self-iterate/toy-basic/cases.json')); s=importlib.util.spec_from_file_location('g','examples/toy/.self-iterate/toy-basic/gates.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert set(m.GATES)=={'is_one_word','matches_expected'}; print('example ok')"
.venv/bin/pytest -q
```
Expected: `example ok`, and full suite green (test count drops by 1 since test_run_case.py removed, offset by the new adapter_generic/cli tests).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: move toy to examples/ (user-layout demo); drop adapters/ + evals/"
```

---

## Task 9: Slash command + plugin README

**Files:**
- Create: `commands/self-iterate.md`
- Modify: `README.md` (rewrite the "Self-iteration loop" section for the plugin shape)

- [ ] **Step 1: Create `commands/self-iterate.md`**

```markdown
---
description: Self-iterate the current repo's agent harness toward a goal until a verifiable condition is met. Usage: /self-iterate toward <goal>
---

# /self-iterate

Usage: `/self-iterate toward <goal>`

Dispatches the `self-iterate` skill for one round toward the eval spec at
`.self-iterate/<goal>/` in the current repo, wrapped in run-until-done (ralph/autopilot)
with the `goal-checker` agent as the reviewer.

## What it does
1. Ensures the Python env is ready (runs `cli.py setup` if `.self-iterate/.venv` is missing).
2. Hands off to the `self-iterate` skill, which stages a worktree, runs the maker → checker →
   goal-checker each round, and writes state to `.loop/iterate/<run_id>/`.
3. Stops when the goal is met (composite ≥ threshold, no gate regression, ≤ max_rounds) or the
   cap is hit. The human merges the winning worktree.

## Before first use
Create `.self-iterate/<goal>/` with `goal.yaml`, `cases.json`, `gates.py`, `judge.md`
(copy `examples/toy/.self-iterate/toy-basic/` as a template). For a non-Claude-CLI agent,
add a `run_case.py` escape hatch.
```

- [ ] **Step 2: Replace the `## Self-iteration loop (the product)` section in `README.md`** with a plugin-oriented version:

```markdown
## self-iterate (the plugin)

This repo **is** a Claude Code plugin that self-iterates any agent's harness
(prompt/skills/tools) until a verifiable goal is met. Design:
[spec](docs/superpowers/specs/2026-06-23-plugin-ization-design.md).

### Install
Place this repo in your Claude Code plugins dir (or your usual plugin-install path).
Requires Python 3.11+. Then in any repo:
```
/self-iterate setup        # bootstraps .self-iterate/.venv + pyyaml/httpx (once)
```

### Use it on your agent
In your agent's repo, write the only thing you need — an eval spec:
```
.self-iterate/<goal>/
  goal.yaml     # threshold, weights, regression, optional agent:/harness: overrides
  cases.json    # your QA set
  gates.py      # your programmatic gates (GATES = {name: fn})
  judge.md      # your LLM-rubric dims
  # optional run_case.py — escape hatch for non-Claude-CLI agents (e.g. a service)
```
Then:
```
/self-iterate toward <goal>
```
A generic adapter handles Claude-native agents (no adapter code): it iterates the standard
harness (`CLAUDE.md`, `AGENTS.md`, `.claude/skills/**`, `.claude/agents/**`) in an isolated
git worktree, runs each case via `claude -p`, and scores with your gates + judge. State lands
in your repo at `.loop/iterate/<run_id>/`. The loop never auto-merges — you merge the winner.

### Point it at a non-Claude agent
Drop a `run_case.py` defining `run_case(case, worktree, harness_paths) -> result` into
`.self-iterate/<goal>/`. The generic runner uses it instead of `claude -p`. That's the only
code a non-Claude agent needs.

### Example
See [`examples/toy/`](examples/toy/) — a one-word-answerer agent + its `.self-iterate/toy-basic/`
eval spec, ready to `/self-iterate toward toy-basic`.
```

- [ ] **Step 3: Commit**

```bash
git add commands/self-iterate.md README.md
git commit -m "feat: add /self-iterate command + rewrite README for plugin shape"
```

---

## Task 10: Full suite + plugin-layout smoke check

**Files:** none (verification + record)

- [ ] **Step 1: Full test suite**

```bash
cd /Users/zhengweijun/agent/loop-iteration
.venv/bin/pytest -q
```
Expected: all green.

- [ ] **Step 2: Plugin-layout smoke**

```bash
.venv/bin/python -c "import json; json.load(open('.claude-plugin/plugin.json')); print('manifest ok')"
.venv/bin/python -m loop_iter.cli --help 2>&1 | head -1
.venv/bin/python -m loop_iter.cli goal-check --eval examples/toy/.self-iterate/toy-basic --run-id smoketest --base examples/toy 2>&1 | tail -3; echo "exit: $?"
```
Expected: `manifest ok`; the cli `--help` prints subcommands; the goal-check on an empty state prints `{"met": false, ... "reason": "no rounds yet"}` and exits 1.

- [ ] **Step 3: Record outcome in `.loop/progress.md`** — append to the `## Done` section:

```markdown
- 2026-06-23 — **Plugin-ization complete.** Repo restructured into a Claude Code plugin
  (`.claude-plugin/` + root `skills/`/`agents/`/`commands/` + bundled `scripts/loop_iter/`).
  Generic adapter (`resolve_harness` + `claude -p` default + `run_case.py` escape hatch +
  unified `cli.py`). Users now write only `.self-iterate/<goal>/`; toy moved to `examples/`.
  Full suite green; plugin-layout smoke passes. Remaining: install-path/distribution decision
  + the maas escape-hatch validation (adapter #2).
```

- [ ] **Step 4: Commit**

```bash
git add .loop/progress.md
git commit -m "docs: record plugin-ization completion in state spine"
```

---

## Self-Review (completed during authoring)

**1. Spec coverage:**
- §4.1 layout (manifest, skills/agents/commands/scripts, examples, bundled Python) → Tasks 1, 2, 8, 9. ✓
- §4.2 generic adapter (resolve_harness, apply_variant, run_case default+escape, config in goal.yaml) → Tasks 3, 4, 6. ✓
- §4.3 user contract + runtime (cli subcommands, state in user repo, /self-iterate) → Tasks 6, 7, 9. ✓
- §4.4 refactor mapping + testing + migration safety → Tasks 1–10 (move-first ordering, each commit green). ✓
- §5 scope (in/out) → maas + marketplace explicitly deferred (Task 10 records it). ✓

**2. Placeholder scan:** No TBD/TODO. Every code step shows full code; every move shows exact commands. The one `<plugin-root>` / `<plugin>/scripts/...` token in the skills is intentional (the skill resolves its own base dir at runtime, like every installed plugin skill) — documented in the self-iterate skill body, not a placeholder.

**3. Type consistency:** `resolve_harness(eval_dir, repo_root) -> list[str]`, `load_run_case(eval_dir) -> callable|None`, `run_case_default(case, worktree, config) -> Result`, `build_agent_cmd(config) -> list[str]`, `snapshot_harness(worktree, harness_paths, dest)` — identical across Tasks 3/4/6 and the skills (Task 7). `run_cases(..., run_case_fn)` now calls `run_case_fn(case, worktree)` consistently in Task 5 (impl), Task 6 (cli closures), and the test stubs. `cli.py` subcommand names (`apply-variant`, `case-run`, `goal-check`, `setup`) match across Tasks 6, 7, 9, 10.

**Ordering note:** Task 5 changes the `run_cases` signature before Task 6's `cli.py` consumes it — correct order. Task 8 deletes `adapters/toy/run_case.py` only after its logic lives in `adapter_generic.run_case_default` (Task 4) and `cli.py` no longer references the toy adapter (Task 6 uses the generic resolver) — safe.
