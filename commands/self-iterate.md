---
description: Self-iterate the current repo's agent harness toward a goal until a verifiable condition is met. Usage: /self-iterate toward <goal>
---

# /self-iterate

Usage: `/self-iterate toward <goal>`

Dispatches the `self-iterate` skill for one round toward the eval spec at
`.self-iterate/<goal>/` in the current repo, wrapped in run-until-done (ralph/autopilot)
with the `goal-checker` agent as the reviewer.

## What it does
1. Ensures the Python env is ready: runs `cli.py setup --eval .self-iterate/<goal>` (once). If
   `goal.yaml` has `agent.venv` (e.g. `.venv`), it uses that venv (which has the agent's own deps,
   e.g. `zai_adk`); otherwise it bootstraps `.self-iterate/.venv`. The chosen interpreter is recorded
   in `.self-iterate/.python`, and `.env` is auto-loaded by the cli — so no manual env sourcing.
2. Hands off to the `self-iterate` skill, which stages a worktree, runs the maker → checker →
   goal-checker each round, and writes state to `.loop/iterate/<run_id>/`.
3. Stops when the goal is met (composite ≥ threshold, no gate regression, ≤ max_rounds) or the
   cap is hit. The human merges the winning worktree.

## Before first use
Create `.self-iterate/<goal>/` with `goal.yaml`, `cases.json`, `gates.py`, `judge.md`
(copy `examples/toy/.self-iterate/toy-basic/` as a template). For a non-Claude-CLI agent,
add a `run_case.py` escape hatch.
