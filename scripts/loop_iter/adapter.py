from __future__ import annotations
import shutil
import subprocess
import tempfile
from pathlib import Path

def _git(repo: str, *args: str) -> str:
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {args} failed: {out.stderr.strip()}")
    return out.stdout.strip()

def apply_variant(repo_root: str, baseline_ref: str, agent_subdir: str) -> str:
    """Create a detached worktree of repo_root at baseline_ref. The maker edits
    <worktree>/<agent_subdir> there; the source repo is never mutated mid-loop.
    Returns the worktree path.

    Refuses if repo_root is not the root of a git repo: `git -C <subdir> worktree add`
    would otherwise silently create a worktree of the *parent* repo, breaking harness
    relative paths (the worktree root would be the parent's tree, not repo_root's)."""
    toplevel = _git(repo_root, "rev-parse", "--show-toplevel")
    if Path(toplevel).resolve() != Path(repo_root).resolve():
        raise RuntimeError(
            f"--base {repo_root!r} must be the root of a git repo, but it is inside "
            f"{toplevel!r}. Run /self-iterate from the agent's own repo root "
            f"(or `git init` one if needed)."
        )
    wt = tempfile.mkdtemp(prefix="loopiter_wt_")
    shutil.rmtree(wt)  # mkdtemp created the dir; worktree add needs a non-existent path
    _git(repo_root, "worktree", "add", "--detach", wt, baseline_ref)
    return wt

def snapshot_variant(worktree: str, agent_subdir: str, dest: str) -> None:
    """Copy the variant's harness subdir to dest (per-round snapshot)."""
    src = Path(worktree, agent_subdir)
    shutil.copytree(src, dest, dirs_exist_ok=True)

def remove_worktree(worktree: str) -> None:
    """Tear down a worktree; never raises (crash-safe cleanup)."""
    try:
        _git(worktree, "worktree", "remove", "--force", worktree)
    except Exception:
        pass
    p = Path(worktree)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
