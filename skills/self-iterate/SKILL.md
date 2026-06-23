---
name: self-iterate
description: Drives ONE round of agent-harness self-iteration for the agent in the current repo. Read state → stage a candidate worktree → dispatch the harness-rewriter (maker) to fix last round's failures on the resolved harness paths → dispatch the case-evaluator (checker) to score it → snapshot + update state → report the goal-checker verdict. The loop is run-until-done (ralph/autopilot) wrapping this skill; goal-checker is the separate reviewer. Use when the user runs "/self-iterate toward <goal>" or says "self-iterate toward <goal>".
---

# self-iterate (one round)

You run exactly one round, in the user's current repo (cwd). The broader loop is driven by run-until-done — you do not loop yourself.

## Inputs
- `goal` — eval name under `.self-iterate/` in cwd.
- `run_id` — current run id. `round` — this round's number (1-based).

## One round
1. **Stage the variant.** Resolve a worktree + harness paths via the bundled CLI (path is relative to this plugin's root):
   ```
   python <plugin-root>/scripts/loop_iter/cli.py apply-variant --eval .self-iterate/<goal> --baseline HEAD
   ```
   Read the printed JSON: `{worktree, harness}`. `harness` is the list of files the maker may edit.
2. **Maker.** Dispatch the `harness-rewriter` agent with `worktree`, `harness` (the paths), and last round's findings (round 1: "cold start — sharpen the baseline harness to satisfy the gates"). It edits only files in `harness`.
3. **Checker.** Dispatch the `case-evaluator` skill on the worktree. It runs:
   ```
   python <plugin-root>/scripts/loop_iter/cli.py case-run --eval .self-iterate/<goal> --worktree <worktree> --run-id <run_id> --round <round>
   ```
   which writes this round's RunScores into `.loop/iterate/<run_id>/scores.json` and returns failing gates + weak dims.
4. **Snapshot + state.** Snapshot the variant's harness files into `.loop/iterate/<run_id>/variants/round_<N>/` (provenance):
   ```
   python <plugin-root>/scripts/loop_iter/cli.py snapshot --eval .self-iterate/<goal> --worktree <worktree> --dest .loop/iterate/<run_id>/variants/round_<N>
   ```
   Append a one-line summary to `.loop/iterate/<run_id>/progress.md`.
5. **Stop-condition handoff.** Run the goal-checker:
   ```
   python <plugin-root>/scripts/loop_iter/cli.py goal-check --eval .self-iterate/<goal> --run-id <run_id> [--best-gate-rates '<json>']
   ```
   Exit 0 = met (stop, surface the best variant); exit 1 = not met (return findings; run-until-done fires the next round).

## Run-until-done
Wrap this skill in **ralph / autopilot**: worker = "run one self-iterate round toward `<goal>`", reviewer = the `goal-checker` agent. The stop condition (composite ≥ threshold, no gate regression, ≤ max_rounds) is judged by an agent that did NOT do the work.

## Rules
- One round only. Maker and checker are different agents; you are the orchestrator.
- State lives in the user's repo (`.loop/iterate/<run_id>/`). The plugin is stateless.
- Source repo is never mutated mid-loop — only the worktree. Merging the winner is the human's call.
