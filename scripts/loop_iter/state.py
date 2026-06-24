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

    @property
    def state_file(self) -> Path:
        return self.run_dir / "state.json"

    @property
    def baseline_file(self) -> Path:
        return self.run_dir / "baseline.json"

    @property
    def report_md(self) -> Path:
        return self.run_dir / "report.md"

    @property
    def winner_diff(self) -> Path:
        return self.run_dir / "winner.diff"

    @property
    def scores(self) -> Path:
        return self.run_dir / "scores.json"

    @property
    def progress(self) -> Path:
        return self.run_dir / "progress.md"

    @property
    def variants_dir(self) -> Path:
        d = self.run_dir / "variants"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _now() -> str:
    from datetime import timezone
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


# ---- scores.json (accumulating rounds) ----
def _load_raw(rp: RunPaths) -> dict:
    if not rp.scores.exists():
        return {"run_id": rp.run_id, "rounds": [], "best_round": None}
    return json.loads(rp.scores.read_text())

def write_scores(rp: RunPaths, data: dict) -> None:
    rp.run_dir.mkdir(parents=True, exist_ok=True)
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
    rp.run_dir.mkdir(parents=True, exist_ok=True)
    rp.progress.write_text(f"# Run {rp.run_id}\n\n{body}\n")


# ---- state.json (phase machine) ----
def write_state(rp: RunPaths, st: dict) -> None:
    rp.run_dir.mkdir(parents=True, exist_ok=True)
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
