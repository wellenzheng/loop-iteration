---
description: Self-iterate the current repo's agent harness toward a goal until a verifiable condition is met. Usage: /self-iterate toward <goal>
---

# /self-iterate

Usage:
- `/self-iterate setup` — interactive: dispatches the `self-iterate-setup` skill, which reads the
  repo, proposes the eval spec (goal.yaml/cases.json/gates.py/rubric.md/quality.md), confirms each
  piece with you, writes it to `.self-iterate/<goal>/`, self-validates, then resolves the Python env
  (`agent.venv` or bootstrap) to `.self-iterate/.python`.
- `/self-iterate start <goal>` — runs the built-in state-machine loop to completion (baseline →
  maker/checker rounds → goal-check → report), persisting everything under
  `.self-iterate/runs/<run_id>/`. `/self-iterate toward <goal>` is an alias.
- `/self-iterate start` calls the cli `setup` handler directly (env-only, non-interactive) if
  `.self-iterate/.python` is missing — it does NOT run the interactive `self-iterate-setup` skill.

## What `start` does
Dispatches the `self-iterate` skill, which loops by advancing an on-disk state machine
(`.self-iterate/runs/<run_id>/state.json`). The cli enforces phase ordering and the `max_rounds` cap
(from `goal.yaml`), so the loop runs until the goal is met or the cap is hit — no external
ralph/autopilot needed. The loop never auto-merges; `report` writes `winner.diff` + `report.md` and
you decide whether to merge the winning worktree.

## Before first use
Create `.self-iterate/<goal>/` with `goal.yaml`, `cases.json`, `gates.py`, `rubric.md`
(copy `examples/toy/.self-iterate/toy-basic/` as a template). For a non-Claude-CLI agent, add a
`run_case.py` escape hatch.
