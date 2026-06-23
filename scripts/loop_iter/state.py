from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass
class RunPaths:
    base: str
    run_id: str

    @property
    def run_dir(self) -> Path:
        return Path(self.base, ".loop", "iterate", self.run_id)

    @property
    def scores(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir / "scores.json"

    @property
    def progress(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir / "progress.md"

    @property
    def variants_dir(self) -> Path:
        d = self.run_dir / "variants"; d.mkdir(parents=True, exist_ok=True)
        return d

def _load_raw(rp: RunPaths) -> dict:
    if not rp.scores.exists():
        return {"run_id": rp.run_id, "rounds": [], "best_round": None}
    return json.loads(rp.scores.read_text())

def write_scores(rp: RunPaths, data: dict) -> None:
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
    rp.progress.write_text(f"# Run {rp.run_id}\n\n{body}\n")
