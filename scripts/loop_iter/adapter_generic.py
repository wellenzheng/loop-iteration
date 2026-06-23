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
