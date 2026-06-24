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


import os
import sys


def _variant_dir(worktree: str, config: dict) -> str:
    """The variant harness dir: worktree itself, or worktree/<variant_subdir>."""
    sub = config.get("variant_subdir")
    return os.path.join(worktree, sub) if sub else worktree


def _sub(template: str, mapping: dict) -> str:
    """Substitute {variant_dir}/{query}/{worktree}-style placeholders in a string."""
    out = template
    for k, v in mapping.items():
        out = out.replace(k, str(v))
    return out


def _normalize_result(raw, case_id: str) -> dict:
    """Coerce an entry's return (str | None | {output,trace,error}) into a Result."""
    if isinstance(raw, dict) and "output" in raw:
        return {"case_id": case_id, "output": str(raw.get("output", "")),
                "trace": raw.get("trace") or {}, "error": raw.get("error")}
    return {"case_id": case_id, "output": str(raw) if raw is not None else "",
            "trace": {}, "error": None}


def run_command_case(case: dict, worktree: str, config: dict) -> dict:
    """Run config['cmd'] with {variant_dir}/{query}/{worktree} substituted; capture stdout.
    Never raises (crash/timeout -> error field)."""
    variant_dir = _variant_dir(worktree, config)
    mapping = {"{variant_dir}": variant_dir,
               "{query}": case.get("query", ""),
               "{worktree}": worktree}
    cmd = [_sub(str(t), mapping) for t in config.get("cmd", [])]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=config.get("timeout", 120))
        output = proc.stdout.strip()
        error = None if proc.returncode == 0 else f"exit {proc.returncode}: {proc.stderr.strip()[:300]}"
    except Exception as exc:
        output, error = "", f"run_case error: {exc!r}"
    return {"case_id": case["id"], "output": output, "trace": {}, "error": error}


import importlib


def run_python_import_case(case: dict, worktree: str, config: dict) -> dict:
    """Import config['module'] (after adding config['module_path'] to sys.path), call
    config['entry'](query=, variant_dir=, **extra); normalize the return. Never raises."""
    variant_dir = _variant_dir(worktree, config)
    for p in config.get("module_path", []):
        ap = os.path.abspath(p)
        if ap not in sys.path:
            sys.path.insert(0, ap)
    try:
        mod = importlib.import_module(config["module"])
        entry = getattr(mod, config.get("entry", "run"))
        raw = entry(query=case.get("query", ""), variant_dir=variant_dir,
                    **(config.get("extra") or {}))
        return _normalize_result(raw, case["id"])
    except Exception as exc:
        return {"case_id": case["id"], "output": "", "trace": {}, "error": f"run_case error: {exc!r}"}


_KNOWN_TYPES = {"claude-p", "command", "python-import", "custom"}


def build_run_case(eval_dir: str, agent_config: dict | None, harness: list):
    """Return a run_case_fn(case, worktree) chosen by agent_config['type'].

    Precedence: command | python-import | claude-p -> that type. custom/omitted ->
    run_case.py if present, else claude-p default. Unknown type -> ValueError.
    """
    cfg = agent_config or {}
    atype = cfg.get("type")
    if atype == "command":
        return lambda case, worktree: run_command_case(case, worktree, cfg)
    if atype == "python-import":
        return lambda case, worktree: run_python_import_case(case, worktree, cfg)
    if atype == "claude-p":
        return lambda case, worktree: run_case_default(case, worktree, cfg)
    if atype is not None and atype not in _KNOWN_TYPES:
        raise ValueError(f"unknown agent.type {atype!r}; expected one of {sorted(_KNOWN_TYPES)} or omit")
    # atype is None or "custom": escape hatch if present, else claude-p default
    user_rc = load_run_case(eval_dir)
    if user_rc is not None:
        return lambda case, worktree: user_rc(case, worktree, harness)
    return lambda case, worktree: run_case_default(case, worktree, cfg)
