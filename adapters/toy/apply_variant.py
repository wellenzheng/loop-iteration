"""Toy adapter apply_variant: wraps loop_iter.adapter with toy-specific paths.
The toy agent's repo root IS this loop-iteration repo; its harness lives at
adapters/toy/agent_files. apply_variant stages a worktree from main."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from loop_iter.adapter import apply_variant as _apply, remove_worktree  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_SUBDIR = "adapters/toy/agent_files"

def apply_variant(baseline_ref: str = "HEAD") -> str:
    return _apply(repo_root=REPO_ROOT, baseline_ref=baseline_ref, agent_subdir=AGENT_SUBDIR)
