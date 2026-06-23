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
