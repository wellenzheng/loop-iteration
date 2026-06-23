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
