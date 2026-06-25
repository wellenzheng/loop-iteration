"""Unified CLI for the self-iterate plugin: apply-variant | case-run | goal-check | setup.
Invoked by the skills as: python <plugin>/scripts/loop_iter/cli.py <cmd> ..."""
from __future__ import annotations
import os
import sys
# Bootstrap: put this package's parent (scripts/) on sys.path so the deferred
# `from loop_iter.X` imports resolve when this file is run as a script from anywhere
# (e.g. `python <plugin>/scripts/loop_iter/cli.py ...`), not just via `python -m`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import argparse
import json
import subprocess
from pathlib import Path


def _apply_variant(args):
    from loop_iter.adapter import apply_variant
    from loop_iter.adapter_generic import resolve_harness
    try:
        wt = apply_variant(repo_root=args.base, baseline_ref=args.baseline, agent_subdir=".")
    except RuntimeError as e:
        raise SystemExit(str(e))
    harness = resolve_harness(args.eval, args.base)
    print(json.dumps({"worktree": wt, "harness": harness}))


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


def _case_run(args):
    import yaml
    from loop_iter.state import RunPaths, append_round
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import resolve_harness, build_run_case
    ev = Path(args.eval)
    goal = yaml.safe_load((ev / "goal.yaml").read_text())
    cases = json.loads((ev / "cases.json").read_text())
    harness = resolve_harness(args.eval, args.base)
    rp = RunPaths(base=args.base, run_id=args.run_id)
    # state-machine: guard eval -> goalcheck BEFORE the expensive run_cases AND before
    # append_round. Guarding first means a wrong-phase refusal leaves scores.json untouched
    # (no inconsistent-state window where scores.json has an extra round but state didn't
    # advance) and skips the costly case evaluation entirely.
    if rp.state_file.exists():
        from loop_iter.state import load_state, advance_phase
        st = load_state(rp)
        if st["phase"] != "eval":
            raise SystemExit(f"phase guard: case-run requires phase=eval, got {st['phase']}")
    rc = build_run_case(args.eval, goal.get("agent", {}), harness)
    from loop_iter.llm_client import chat as llm_call
    out = run_cases(cases, args.worktree, str(ev / "gates.py"),
                    (ev / "judge.md").read_text(), goal["weights"],
                    run_case_fn=rc, llm_call=llm_call)
    out["round"] = args.round
    # harness-quality guardrail (opt-in via quality.md); score the VARIANT's harness in the worktree
    out["quality"], out["quality_dims"] = _compute_quality(ev, args.base, args.worktree, cases, llm_call)
    if rp.state_file.exists():
        (rp.run_dir / "quality.json").write_text(
            json.dumps({"round": args.round, "quality": out["quality"],
                        "quality_dims": out["quality_dims"]}, indent=2, ensure_ascii=False))
        append_round(rp, out)
        advance_phase(rp, "eval", "goalcheck")
    else:
        append_round(rp, out)
    print(json.dumps({"round": args.round, "composite": out["composite"],
                      "gate_pass_rates": out["gate_pass_rates"]}))


def _goal_check(args):
    from loop_iter.state import RunPaths
    from loop_iter.goal_check import check_latest, check_and_advance
    rp = RunPaths(base=args.base, run_id=args.run_id)
    best = json.loads(args.best_gate_rates) if args.best_gate_rates else None
    goal_path = str(Path(args.eval, "goal.yaml"))
    if rp.state_file.exists():
        try:
            v = check_and_advance(rp, goal_path, best)
        except RuntimeError as e:
            raise SystemExit(str(e))
    else:
        v = check_latest(rp, goal_path, best)
    print(json.dumps(v, indent=2))
    raise SystemExit(0 if v["met"] else 1)


def _read_agent_venv(goal_path):
    """Return the agent.venv value from goal.yaml, or None. Uses pyyaml if available,
    else a minimal line scan — so `setup` works under a python WITHOUT pyyaml (the very
    first setup runs before the agent venv is recorded, possibly under a bare system python)."""
    text = goal_path.read_text()
    try:
        import yaml
        spec = yaml.safe_load(text) or {}
        return (spec.get("agent") or {}).get("venv")
    except ImportError:
        import re
        m = re.search(r'^[ \t]*venv:[ \t]*([^\s#]+)', text, re.M)  # the only `venv:` key (under agent:)
        return m.group(1) if m else None


def _setup(args):
    # Resolve the interpreter: agent.venv (if set + exists) else bootstrap .self-iterate/.venv.
    venv_dir = None
    if args.eval:
        goal_path = Path(args.eval, "goal.yaml")
        if goal_path.exists():
            av = _read_agent_venv(goal_path)
            if av and Path(args.base, av, "bin", "python").exists():
                venv_dir = Path(args.base, av)
    bootstrapped = False
    if venv_dir is None:
        venv_dir = Path(args.base, ".self-iterate", ".venv")
        if not venv_dir.exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        bootstrapped = True
    py = str(venv_dir / "bin" / "python")
    # Only a freshly-bootstrapped venv needs pyyaml+httpx installed (via `python -m pip`).
    # An agent's OWN venv (e.g. uv-managed, no pip) is assumed to already have its deps —
    # don't force-install into it (would fail; and they're the agent owner's responsibility).
    if bootstrapped:
        subprocess.run([py, "-m", "pip", "install", "-q", "pyyaml", "httpx"], check=True)
    dotpy = Path(args.base, ".self-iterate", ".python")
    dotpy.parent.mkdir(parents=True, exist_ok=True)
    dotpy.write_text(py)
    print(json.dumps({"python": py, "venv": str(venv_dir), "bootstrapped": bootstrapped,
                      "deps": ["pyyaml", "httpx"]}))


def _init(args):
    import yaml
    from loop_iter.state import RunPaths, init_state
    rp = RunPaths(base=args.base, run_id=args.run_id)
    if rp.state_file.exists():
        raise SystemExit(f"run already initialized: {rp.state_file} (resume with `start`, do not re-init)")
    goal_path = Path(args.eval, "goal.yaml")
    spec = yaml.safe_load(goal_path.read_text())
    st = init_state(rp, args.goal, spec["max_rounds"])
    print(json.dumps({"run_id": args.run_id, "phase": st["phase"], "max_rounds": st["max_rounds"]}))


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


def _baseline(args):
    import yaml
    from loop_iter.state import RunPaths, load_state, advance_phase
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import resolve_harness, build_run_case
    from loop_iter.llm_client import chat as llm_call
    rp = RunPaths(base=args.base, run_id=args.run_id)
    rp.run_dir.mkdir(parents=True, exist_ok=True)
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
    out["quality"], out["quality_dims"] = _compute_quality(ev, args.base, args.base, cases, llm_call)
    rp.baseline_file.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    advance_phase(rp, "baseline", "maker",
                  updates={"round": 1, "baseline_composite": out["composite"],
                           "baseline_quality": out["quality"]})
    print(json.dumps({"baseline_composite": out["composite"],
                      "baseline_quality": out["quality"], "phase": "maker", "round": 1}))


def _report(args):
    import difflib
    from loop_iter.state import RunPaths, load_state, load_scores
    from loop_iter.adapter_generic import resolve_harness
    rp = RunPaths(base=args.base, run_id=args.run_id)
    rp.run_dir.mkdir(parents=True, exist_ok=True)
    st = load_state(rp)
    data = load_scores(rp)
    rounds = data.get("rounds", [])
    if not rounds:
        raise SystemExit("report: no rounds recorded")
    best_round = data.get("best_round") or rounds[-1]["round"]
    best = next((r for r in rounds if r["round"] == best_round), None)
    if best is None:
        raise SystemExit(f"report: best_round {best_round} not found in recorded rounds")
    snap_dir = rp.variants_dir / f"round_{best_round}"
    harness = resolve_harness(args.eval, args.base)
    diff_lines: list[str] = []
    for rel in harness:
        base_path = Path(args.base, rel)
        snap_path = snap_dir / rel
        if not snap_path.exists():
            print(f"warning: no snapshot for {rel} at round {best_round}; skipping", file=sys.stderr)
            continue
        base_lines = base_path.read_text().splitlines(keepends=True) if base_path.exists() else []
        snap_lines = snap_path.read_text().splitlines(keepends=True)
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


def _load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE from .env into os.environ via setdefault (explicit env wins).
    Shell-safe python parse (zsh `source` chokes on some .env lines). No-op if absent."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv=None):
    _load_dotenv()
    ap = argparse.ArgumentParser(prog="python -m loop_iter.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("apply-variant")
    s.add_argument("--eval", required=True)
    s.add_argument("--base", default=".")
    s.add_argument("--baseline", default="HEAD")
    s.set_defaults(func=_apply_variant)

    s = sub.add_parser("snapshot")
    s.add_argument("--eval", required=True)
    s.add_argument("--worktree", required=True)
    s.add_argument("--dest", required=True)
    s.add_argument("--base", default=".")
    s.add_argument("--run-id", default=None)
    s.set_defaults(func=_snapshot)

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
    s.add_argument("--eval", default=None, help="eval dir (reads goal.yaml agent.venv)")
    s.add_argument("--base", default=".")
    s.set_defaults(func=_setup)

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

    s = sub.add_parser("report")
    s.add_argument("--eval", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--base", default=".")
    s.set_defaults(func=_report)

    a = ap.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
