---
name: self-iterate
description: Drives the built-in state-machine self-iteration loop for the agent in the current repo (baseline → maker/checker rounds → goal-check → report), advancing an on-disk state machine at .self-iterate/runs/<run_id>/state.json. The cli enforces phase ordering and the max_rounds cap; no external ralph/autopilot needed. Use when the user runs "/self-iterate toward <goal>" or "/self-iterate start <goal>".
---

# self-iterate (state-machine loop)

You drive the built-in self-iteration loop in the user's current repo (cwd), advancing an on-disk
state machine at `.self-iterate/runs/<run_id>/state.json`. The cli enforces phase ordering — you
cannot skip steps. You loop until `phase == done`.

## Inputs
- `goal` — eval name under `.self-iterate/` in cwd.
- `run_id` — a fresh id for this run (e.g. `YYYYMMDD_HHMMSS_shorttag`).

## Interpreter
```
PY=$(cat .self-iterate/.python 2>/dev/null || echo python)
```
Use `"$PY"` for every cli call below. `<plugin>` = this plugin's root.

## Loop
1. **Init** (once): `"$PY" <plugin>/scripts/loop_iter/cli.py init --goal <goal> --eval .self-iterate/<goal> --run-id <run_id>`. Creates `state.json` at `phase=baseline`.
2. **Baseline** (once): `"$PY" <plugin>/scripts/loop_iter/cli.py baseline --eval .self-iterate/<goal> --run-id <run_id>`. Scores the unmodified harness, writes `baseline.json`, advances to `phase=maker`, `round=1`.
   *(If `.self-iterate/<goal>/quality.md` exists, the baseline and each `case-run` also score the
   harness files themselves on a quality rubric → `baseline_quality` / per-round `quality.json`. A
   round whose quality regresses below `baseline_quality − quality_tolerance` (default 0.5) cannot
   satisfy `met` and cannot be the best variant — the guardrail against overfitting/harness rot.
   No `quality.md` → guardrail inactive.)*
3. **Per round, while `phase != done`:**
   a. **Stage + maker.** `apply-variant` for a worktree, then dispatch the `harness-rewriter` agent on the worktree (round 1: "cold start — sharpen the baseline harness to satisfy the gates"; later rounds: pass the failing gates + weak dims from the previous `case-run`).
   b. **Snapshot + advance.** `"$PY" <plugin>/scripts/loop_iter/cli.py snapshot --eval .self-iterate/<goal> --worktree <worktree> --dest .self-iterate/runs/<run_id>/variants/round_<N> --run-id <run_id>`. Snapshots the variant and advances `maker -> eval`.
   c. **Eval + advance.** `"$PY" <plugin>/scripts/loop_iter/cli.py case-run --eval .self-iterate/<goal> --worktree <worktree> --run-id <run_id> --round <N>`. Runs cases + judge, writes this round into `scores.json`, advances `eval -> goalcheck`.
   d. **Goal-check + advance.** `"$PY" <plugin>/scripts/loop_iter/cli.py goal-check --eval .self-iterate/<goal> --run-id <run_id>`. Computes the verdict and advances: `met` or `round >= max_rounds` -> `phase=done`; otherwise -> `phase=maker`, `round++`.
4. **Report** (at `done`): `"$PY" <plugin>/scripts/loop_iter/cli.py report --eval .self-iterate/<goal> --run-id <run_id>`. Writes `winner.diff` + `report.md`. Surface the best round + whether `met`.

## Resume
Re-invoking `start` reads `state.json` and resumes from the current phase. If you stall mid-round,
re-run `start` with the same `<run_id>` — the cli picks up at the recorded phase.

## Rules
- You advance phases only via the cli (each command checks + writes `state.json`). Never edit
  `state.json` by hand.
- Maker and checker are different agents; you are the orchestrator.
- The source repo is never mutated mid-loop — only the worktree. Merging the winner is the human's call.
- Stop only when `phase == done`. The cli enforces the `max_rounds` cap; you cannot loop past it.
