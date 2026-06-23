---
name: self-iterate
description: Drives ONE round of agent-harness self-iteration. Read state → stage a candidate variant worktree → dispatch the harness-rewriter (maker) to fix last round's failures → dispatch the case-evaluator (checker) to score it → snapshot the variant and update state → report findings + whether the goal-checker says met. The loop itself is run-until-done (ralph/autopilot) wrapping this skill; goal-checker is the separate reviewer. Use when the user says "self-iterate <agent> toward <goal>" or when run-until-done fires a round.
---

# self-iterate (one round)

You run exactly one round. The broader loop (repeating until the goal is met) is driven by
run-until-done — you do not loop yourself.

## Inputs (from the loop driver / user)
- `agent` — adapter name under `adapters/` (e.g. `toy`).
- `goal` — eval name under `evals/` (e.g. `toy-basic`).
- `run_id` — the current run's id (timestamp+hex).
- `round` — this round's number (1-based).

## One round
1. **Read state.** Open `.loop/iterate/<run_id>/scores.json`. On round 1 there are no prior
   findings; on round N>1 the maker needs last round's failing gates + weak dims.
2. **Stage the variant.** Run the adapter's `apply_variant` to get an isolated worktree from the
   baseline (HEAD). The maker will edit the harness there; source is never touched mid-loop.
   ```
   python -c "import sys; sys.path.insert(0,'adapters/<agent>'); import apply_variant as a; print(a.apply_variant())"
   ```
   Capture the printed worktree path.
3. **Maker.** Dispatch the `harness-rewriter` sub-agent with the worktree + last round's findings
   (round 1: findings = "cold start, sharpen the baseline harness to satisfy the gates"). It edits
   the harness files in the worktree.
4. **Checker.** Dispatch the `case-evaluator` skill on the worktree (eval = `evals/<goal>`). It
   writes this round's RunScores to state and returns failing gates + weak dims.
5. **Snapshot + state.** Copy the variant's harness subdir to
   `.loop/iterate/<run_id>/variants/round_<N>/` (provenance). Append a one-line summary to
   `.loop/iterate/<run_id>/progress.md` (round N: composite, best so far).
6. **Stop-condition handoff.** Run the goal-checker:
   ```
   python -m loop_iter.goal_check --eval evals/<goal> --run-id <run_id> \
     --best-gate-rates '<best so far, or omit on round 1>'
   ```
   Report its verdict. If `met`, surface the best variant (which `variants/round_*` won) and stop.
   If not met and under `max_rounds`, return the findings so run-until-done fires round N+1.

## How to drive the whole loop (run-until-done)
Wrap this skill in **ralph / autopilot** (OMC): the *worker* is "run one self-iterate round for
`<agent>` toward `<goal>`", and the *verification reviewer* is the `goal-checker` sub-agent. The
stop condition (composite ≥ threshold, no gate regression, ≤ max_rounds) is the reviewer's check,
judged by an agent that did NOT do the work — the maker/checker split applied to the stop condition.

For interactive control, run single rounds by hand and read `progress.md` between them.

## Rules
- One round only. Do not loop.
- The maker and the checker are different agents. You are the orchestrator, neither.
- Source repo is never mutated mid-loop — only the worktree. Merging the winner is the human's call.
