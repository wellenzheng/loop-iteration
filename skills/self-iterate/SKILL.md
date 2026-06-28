---
name: self-iterate
description: Drives the built-in state-machine self-iteration loop for the agent in the current repo (baseline → maker/checker rounds → goal-check → report), advancing an on-disk state machine at .self-iterate/runs/<run_id>/state.json. The cli enforces phase ordering and the max_rounds cap; no external ralph/autopilot needed. Use when the user runs "/self-iterate" (shows usage), "/self-iterate toward <goal>", or "/self-iterate start <goal>".
---

# self-iterate (state-machine loop)

You drive the built-in self-iteration loop in the user's current repo (cwd), advancing an on-disk
state machine at `.self-iterate/runs/<run_id>/state.json`. The cli enforces phase ordering — you
cannot skip steps. You loop until `phase == done`.

## Usage
- `/self-iterate` (no args) → show this usage + the available subcommands.
- `/self-iterate start <goal>` or `/self-iterate toward <goal>` → run the loop to completion.
- `/self-iterate setup` → dispatch the `self-iterate-setup` skill (interactive eval-spec scaffolding).

If invoked with no `<goal>`, ask the user which goal under `.self-iterate/` to run (list them).

## Inputs
- `goal` — eval name under `.self-iterate/` in cwd.
- `run_id` — a fresh id for this run (e.g. `YYYYMMDD_HHMMSS_shorttag`).

## Interpreter
```
PY=$(cat .self-iterate/.python 2>/dev/null || echo python)
```
Use `"$PY"` for every cli call below. `<plugin>` = this plugin's root.

## Loop
**Start the dashboard (automatic).** Before init, launch the dashboard in the background — it
auto-opens the browser so the user can watch the loop live:
```
"$PY" <plugin>/scripts/loop_iter/cli.py dashboard --eval .self-iterate/<goal> --run-id <run_id> --base . &
```
It prints a URL (e.g. `http://127.0.0.1:<port>`) and opens it in the browser automatically. The
page polls every 1.5s and shows live progress, per-round scores, quality dims, case comparison, and
the winner diff. The dashboard is read-only; it never drives the loop. Tell the user the URL in case
the browser doesn't auto-open.

1. **Init** (once): `"$PY" <plugin>/scripts/loop_iter/cli.py init --goal <goal> --eval .self-iterate/<goal> --run-id <run_id>`. Creates `state.json` at `phase=baseline`.
2. **Baseline** (once): `"$PY" <plugin>/scripts/loop_iter/cli.py baseline --eval .self-iterate/<goal> --run-id <run_id>`. Scores the unmodified harness, writes `baseline.json`, advances to `phase=maker`, `round=1`.
   *(If goal.yaml sets `quality_target`, quality becomes an auxiliary optimization target: the
   maker also drives harness 规范度 toward the target. In the baseline phase AND each eval phase,
   dispatch the `quality-judge` agent IN PARALLEL with case-evaluation — the case-run step runs cases
   (output), quality-judge reads the variant harness (clarity/maintainability + maker_feedback);
   they're independent. case-run/baseline compute only the programmatic `no_overfit` when
   `quality_target` is set; the sub-agent provides the LLM dims. After both return: write the
   quality-judge's JSON to `.self-iterate/runs/<run_id>/quality_judge.json` (or
   `quality_judge_baseline.json` for baseline), then run:
   `quality-merge --eval ... --run-id ... --baseline --from quality_judge_baseline.json` (baseline)
   or `--round <N> --from quality_judge.json` (eval) — it merges the sub-agent's LLM dims with the
   programmatic no_overfit into quality.json/baseline.json + the round's quality. Then goal-check
   (met now requires quality ≥ quality_target). For the maker next round, pass the failing gates +
   weak output-judge dims + the quality-judge's `maker_feedback` + weak quality dims — two-phase:
   gates first, then harness 规范度. No `quality_target` → current behavior, no quality-judge.)*
   *(If `.self-iterate/<goal>/quality.md` exists, the baseline and each `case-run` also score the
   harness files themselves on a quality rubric → `baseline_quality` / per-round `quality.json`. A
   round whose quality regresses below `baseline_quality − quality_tolerance` (default 0.5) cannot
   satisfy `met` and cannot be the best variant — the guardrail against overfitting/harness rot.
   The `no_overfit` dimension is detected programmatically (hardcoded-answer check), so it stays
   reliable even when the LLM quality-judge degrades.
   No `quality.md` → guardrail inactive.)*
3. **Per round, while `phase != done`:**
   a. **Stage + maker.** `apply-variant` for a worktree, then dispatch the `harness-rewriter` agent on the worktree (round 1: "cold start — sharpen the baseline harness to satisfy the gates"; later rounds: pass the failing gates + weak dims from the previous `case-run`). When `quality_target` is set, also pass the previous round's `maker_feedback` + weak quality dims (read from `.self-iterate/runs/<run_id>/quality.json`).
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
