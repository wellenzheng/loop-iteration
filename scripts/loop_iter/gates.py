from __future__ import annotations
import importlib.util
from pathlib import Path

def load_gates(gates_path: str) -> dict[str, callable]:
    """Load a user gates module defining GATES = {name: fn(result, case) -> {passed: bool}}."""
    p = Path(gates_path).resolve()
    spec = importlib.util.spec_from_file_location(f"_gates_{p.stem}_{p.stat().st_mtime_ns}", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    if not hasattr(mod, "GATES") or not isinstance(mod.GATES, dict):
        raise ValueError(f"{gates_path} must define GATES = {{name: fn}}")
    return dict(mod.GATES)


def run_gates(result: dict, case: dict, gates: dict[str, callable]) -> list[dict]:
    """Run every gate; a gate that raises counts as failed (never crashes the round)."""
    out: list[dict] = []
    for name, fn in gates.items():
        try:
            verdict = fn(result, case)
            passed = bool(verdict.get("passed", False))
        except Exception:
            passed = False
        out.append({"gate": name, "passed": passed})
    return out
