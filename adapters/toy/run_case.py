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
