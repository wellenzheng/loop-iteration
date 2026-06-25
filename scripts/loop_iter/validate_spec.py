"""Static validation of a .self-iterate/<goal>/ eval spec. The setup skill calls this after writing
the spec to self-verify; `validate-spec` cli wraps it. Problems are fatal (invalid spec); warnings
are non-fatal (optional pieces absent)."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path


_VALID_AGENT_TYPES = {"claude-p", "command", "python-import", "custom"}


def _load_gates(gates_path: Path):
    """Import gates.py and return its GATES dict. Raises if gates.py fails to import OR has no GATES."""
    spec = importlib.util.spec_from_file_location("_validate_gates", gates_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # raises SyntaxError / import-time error
    if not hasattr(mod, "GATES"):
        raise AttributeError("GATES not defined")
    return mod.GATES


def validate_spec(eval_dir: str) -> dict:
    """Return {'valid': bool, 'problems': [str], 'warnings': [str]} for the spec in eval_dir."""
    d = Path(eval_dir)
    problems: list[str] = []
    warnings: list[str] = []

    # goal.yaml
    goal_path = d / "goal.yaml"
    if not goal_path.exists():
        problems.append("goal.yaml: missing")
        goal = {}
    else:
        try:
            import yaml
        except ImportError:
            problems.append("pyyaml not installed (run: pip install pyyaml) - cannot parse goal.yaml")
            goal = {}
        else:
            try:
                goal = yaml.safe_load(goal_path.read_text()) or {}
            except Exception as e:
                problems.append(f"goal.yaml: unparseable ({e})")
                goal = {}
            if not isinstance(goal, dict):
                problems.append("goal.yaml: must be a mapping")
                goal = {}
    # goal is now always a dict (possibly empty); run checks
    if not isinstance(goal.get("threshold"), (int, float)) or isinstance(goal.get("threshold"), bool):
        problems.append("goal.yaml: threshold must be a number")
    mr = goal.get("max_rounds")
    if isinstance(mr, bool) or not isinstance(mr, int) or mr < 1:
        problems.append("goal.yaml: max_rounds must be a positive int")
    w = goal.get("weights")
    if not isinstance(w, dict) or not w:
        problems.append("goal.yaml: weights must be a non-empty dict")
    agent = goal.get("agent") or {}
    atype = agent.get("type")
    if atype is not None and atype not in _VALID_AGENT_TYPES:
        problems.append(f"goal.yaml: agent.type {atype!r} not in {sorted(_VALID_AGENT_TYPES)}")
    if atype is None:
        warnings.append("goal.yaml: agent.type unset -> defaults to claude-p")
    if atype == "command" and not agent.get("cmd"):
        warnings.append("goal.yaml: agent.type=command but no agent.cmd set")
    if atype == "python-import" and not (agent.get("module") and agent.get("entry")):
        warnings.append("goal.yaml: agent.type=python-import but agent.module/entry unset")

    # cases.json
    cases_path = d / "cases.json"
    if not cases_path.exists():
        problems.append("cases.json: missing")
    else:
        try:
            cases = json.loads(cases_path.read_text())
        except Exception as e:
            problems.append(f"cases.json: unparseable ({e})")
            cases = None
        if cases is not None:
            if not isinstance(cases, list) or not cases:
                problems.append("cases.json: must be a non-empty list")
            else:
                for i, c in enumerate(cases):
                    if not isinstance(c, dict) or "id" not in c or "query" not in c:
                        problems.append(f"cases.json: case #{i} must have 'id' and 'query'")

    # gates.py
    gates_path = d / "gates.py"
    if not gates_path.exists():
        problems.append("gates.py: missing")
    else:
        try:
            gates = _load_gates(gates_path)
        except Exception as e:
            problems.append(f"gates.py: {e}")
            gates = None
        if gates is not None:
            if not isinstance(gates, dict) or not gates:
                problems.append("gates.py: GATES must be a non-empty dict")
            else:
                for name, fn in gates.items():
                    if not callable(fn):
                        problems.append(f"gates.py: GATES[{name!r}] is not callable")

    # judge.md
    judge_path = d / "judge.md"
    if not judge_path.exists() or not judge_path.read_text().strip():
        problems.append("judge.md: missing or empty")

    # quality.md (optional)
    qpath = d / "quality.md"
    if not qpath.exists():
        warnings.append("quality.md: absent -> quality guardrail inactive")
    elif not qpath.read_text().strip():
        problems.append("quality.md: empty")

    return {"valid": not problems, "problems": problems, "warnings": warnings}
