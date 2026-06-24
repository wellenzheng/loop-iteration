---
description: Self-iterate the current repo's agent harness toward a goal until a verifiable condition is met. Usage: /self-iterate toward <goal>
---

# /self-iterate

Usage:
- `/self-iterate setup` — interactive: reads the repo, proposes the eval spec, confirms with you,
  writes `.self-iterate/<goal>/`, then resolves the Python env (`agent.venv` or bootstrap) to
  `.self-iterate/.python`. (The interactive proposer is a separate skill; until it lands, hand-write
  the spec from `examples/toy/.self-iterate/toy-basic/`.)
- `/self-iterate start <goal>` — runs the built-in state-machine loop to completion (baseline →
  maker/checker rounds → goal-check → report), persisting everything under
  `.self-iterate/runs/<run_id>/`. `/self-iterate toward <goal>` is an alias.
- `/self-iterate setup` (env only) is still run once automatically before `start` if `.self-iterate/.python`
  is missing.

## What `start` does
Dispatches the `self-iterate` skill, which loops by advancing an on-disk state machine
(`.self-iterate/runs/<run_id>/state.json`). The cli enforces phase ordering and the `max_rounds` cap
(from `goal.yaml`), so the loop runs until the goal is met or the cap is hit — no external
ralph/autopilot needed. The loop never auto-merges; `report` writes `winner.diff` + `report.md` and
you decide whether to merge the winning worktree.

## Before first use
Create `.self-iterate/<goal>/` with `goal.yaml`, `cases.json`, `gates.py`, `judge.md`
(copy `examples/toy/.self-iterate/toy-basic/` as a template). For a non-Claude-CLI agent, add a
`run_case.py` escape hatch.
