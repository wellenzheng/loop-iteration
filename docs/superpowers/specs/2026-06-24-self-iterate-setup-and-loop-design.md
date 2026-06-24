# self-iterate setup + built-in loop — Design

- **Date:** 2026-06-24
- **Status:** Approved (brainstormed), pending implementation plan
- **Project:** `loop-iteration` (the `self-iterate` plugin)
- **Builds on:** [Plugin-ization](2026-06-23-plugin-ization-design.md) + [Adapter typing](2026-06-24-adapter-typing-design.md) + [Out-of-the-box](2026-06-24-out-of-the-box-design.md)

## 1. Goal & motivation

The plugin today runs the optimization loop (worktree → maker → checker → goal-checker) but is **not
out-of-the-box**: the user must hand-write the entire eval spec (`goal.yaml`/`cases.json`/`gates.py`/
`judge.md`), and the loop's run-until-done heartbeat is delegated to an external `ralph`/`autopilot`
that may not exist — so `/self-iterate toward` actually runs one round and stops.

This spec closes both gaps:

- **`/self-iterate setup`** — an interactive skill that reads the repo, proposes the eval spec, confirms
  with the user, and writes it to `.self-iterate/<goal>/`.
- **`/self-iterate start <goal>`** — a built-in loop driven by an **on-disk state machine** (no external
  ralph/autopilot). The skill executes the current phase each invocation; the cli enforces phase
  ordering so Claude cannot skip steps. Adds an explicit baseline step, a harness-quality guardrail, a
  diff+report, and moves all run output under `.self-iterate/runs/<run_id>/`.

## 2. Key decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| D1 | **`setup` is an interactive skill**, not a cli subcommand. It reads the repo, proposes `goal.yaml`/`cases.json`/`gates.py`/`judge.md`/`quality.md` drafts, confirms each with the user, writes them, then calls the existing cli `setup` (venv resolution). | Reading a repo and proposing gates/rubric is LLM work a Python cli cannot do. User confirmation before generation guards against cognitive surrender on auto-generated acceptance criteria. |
| D2 | **`start` drives a built-in loop via an on-disk state machine.** No external ralph/autopilot, no `/loop` watchdog (deferred). The skill reads `state.json` and executes the current phase; the cli enforces phase ordering. maker/checker stay as in-session agents (rich, dogfoods the plugin's own agent system). | Keeps rich sub-agents + dogfooding while guaranteeing step ordering, resumability, and idempotency via disk state. `/loop` is cadence-based (wrong shape for run-until-done); a watchdog is deferred until walk-away is needed. |
| D3 | **Stop conditions are strict: only `goal-check` exit 0 (met) OR `round >= max_rounds`.** No early-stop on plateau. `max_rounds` comes from `goal.yaml`. | User requirement: "如果没达到验收标准，则一定要循环直到达到验收标准或最大循环次数". |
| D4 | **Explicit baseline step before round 1.** Score the unmodified harness (cases + quality) → `baseline.json`. All regression checks and the report delta use it as the reference. | Gives a real before/after; makes goal-checker's "no regression" meaningful. |
| D5 | **harness quality is a guardrail + tiebreak, NOT a main objective.** A `quality.md` rubric judges the harness files themselves; scored in parallel with case-eval each round. Quality regression below baseline (− tolerance) rejects the variant even if eval score rose; ties between variants broken by quality. Quality does not enter the composite. | A harness can game gates while getting messier (hardcoding answers). Modeling quality as a constraint prevents optimizing for pretty prompts at the cost of task performance; it also naturally penalizes overfitting. |
| D6 | **Run output moves from `.loop/iterate/<run_id>/` to `.self-iterate/runs/<run_id>/`.** Input spec stays at `.self-iterate/<goal>/`. | User requirement: all produced artifacts persist under `.self-iterate/`. Input vs output are still separated by subdirectory. |
| D7 | **No parallel candidate variants; no early-stop.** Single variant per round. | YAGNI until single-variant loop is proven. |
| D8 | **A real-time interactive HTML dashboard is the primary report; a static `report.md` + `winner.diff` are kept as offline archive.** A new cli `dashboard` subcommand serves a stdlib HTTP server that watches the run dir; the page polls `/api/state` and re-renders live as the state machine writes each phase. Five panels: live progress, results overview, quality ratings, case comparison, diff. Read-only view over the state machine's writes — never drives the loop. | Directly serves "实时进度/结果总揽/diff/规范评级/优化case对比"; the state machine already writes everything to disk, so the dashboard is a pure view — clean separation, dashboard crashes cannot affect loop guarantees. |

## 3. Architecture

### 3.1 Two commands

- `/self-iterate setup` → dispatches a new `self-iterate-setup` **skill** (interactive). Output: a
  complete `.self-iterate/<goal>/` eval spec. Then calls `cli.py setup --eval <goal>` (existing venv
  resolution) so `.self-iterate/.python` is ready.
- `/self-iterate start <goal>` → dispatches the `self-iterate` skill, which now **loops** by reading
  `state.json` and executing the current phase until `phase == done`. `toward <goal>` remains as an alias
  for `start`.

### 3.2 The state machine (D2)

State lives at `.self-iterate/runs/<run_id>/state.json`:

```json
{
  "goal": "<goal>",
  "run_id": "<id>",
  "round": 0,
  "max_rounds": 5,
  "phase": "init | baseline | maker | eval | goalcheck | done",
  "met": false,
  "baseline_composite": null,
  "baseline_quality": null,
  "best": { "round": null, "composite": null, "worktree": null },
  "started_at": null,
  "updated_at": null
}
```

Phases, executed in order, looping on `maker → eval → goalcheck`:

```
init      → create run dir + state.json (round=0, max_rounds from goal.yaml, phase=baseline)
baseline  → score unmodified HEAD harness (cases + quality) → baseline.json; round=1; phase=maker
maker     → apply-variant (worktree from baseline); dispatch harness-rewriter agent; snapshot variant;
            phase=eval
eval      → dispatch case-evaluator (cases → scores.json) ∥ quality-judge (harness → quality.json);
            phase=goalcheck
goalcheck → cli goal-check (exit code). met? → phase=done, met=true.
                              not met & round < max_rounds? → round++; phase=maker.
                              not met & round >= max_rounds? → phase=done, met=false.
done      → cli report (diff + markdown); surface best variant; stop.
```

**The skill** reads `state.json`, executes the current phase (dispatching agents / calling cli), then
asks the cli to advance the phase. **The cli** is the guardrail: each phase's cli command checks
`state.phase` matches and refuses out-of-order calls; phase transitions are atomic writes that require
the prior phase's output artifact to exist.

### 3.3 Hard invariants the cli enforces (the actual "guarantee")

The state machine's guarantee comes from cli checks, not from Claude following prose:

- `baseline` output (`baseline.json`) must exist before round-1 `maker`/`goalcheck` proceed.
- `goalcheck` refuses if the current round's `scores.json` + `quality.json` are absent (eval cannot be
  skipped).
- `goal-check` computes `met` from scores + `goal.yaml` threshold + regression-vs-baseline; `max_rounds`
  is read from `goal.yaml`; if `round >= max_rounds` and not met, cli forces `done`. Claude cannot loop
  past the cap or falsely claim met.
- Re-invoking `start` reads `state.json` and resumes from the current phase (idempotent: a phase whose
  output already exists is re-used, not re-run). This is how the loop survives Claude stalling mid-run.

### 3.4 Baseline step (D4)

A new cli subcommand `baseline --eval <goal> --run-id <id>` runs the case-evaluator + quality-judge on the
**unmodified** harness (no worktree, or a worktree checked out at `baseline` ref). Writes `baseline.json`
(composite, gate_pass_rates, quality) into the run dir and populates `baseline_composite` /
`baseline_quality` in `state.json`. Executed once, in the `baseline` phase, before any maker runs.

### 3.5 Harness-quality guardrail (D5)

- New eval-spec file `quality.md` — a rubric judging the harness files themselves (structure, no
  hardcoding, maintainability, no case-specific overfitting). Generated/proposed by `setup`.
- The quality-judge reuses the `judge.py` machinery on the harness file contents (not agent outputs),
  producing a 0–10 `quality` score per round → `quality.json`.
- `eval` phase dispatches case-evaluator and quality-judge **in parallel**.
- **Guardrail rule** (in `goal_check.py`): if a round's `quality < baseline_quality − tolerance`
  (tolerance from `goal.yaml`, default 0.5), the round is treated as a regression — it cannot be selected
  as `best` and does not satisfy `met`, even if its composite rose.
- **Tiebreak rule**: when choosing `best` among rounds with equal composite, prefer higher quality.
- Quality is **not** added to the composite (the main objective stays gates + case-judge dims).

### 3.6 State location migration (D6)

`state.py` `RunPaths` changes base from `.loop/iterate/<run_id>/` to `.self-iterate/runs/<run_id>/`.
Per-round artifacts: `scores.json`, `quality.json`, `variants/round_<N>/` (harness snapshot),
`baseline.json`, `state.json`, `progress.md`, final `report.md` + `winner.diff`. Existing tests under
`.loop/...` paths are updated. (`.loop/progress.md` — the project's own dev spine — is unchanged; that is
the loop-iteration repo's state, separate from a target agent's run state.)

### 3.7 Report: real-time dashboard + static archive (D8)

**Real-time dashboard** — new cli subcommand `dashboard --eval <goal> --run-id <id>`:
- A stdlib-only `http.server` (no external deps, offline-capable) that watches
  `.self-iterate/runs/<run_id>/` and serves a single-page app (`index.html` + vanilla JS, no build step)
  plus a `/api/state` endpoint that merges `state.json` + `baseline.json` + each round's
  `scores.json`/`quality.json`/snapshot into one payload.
- The page polls `/api/state` every 1–2s and re-renders. (SSE deferred — polling is stdlib-simple and
  sub-second-to-few-seconds lag is fine for a loop whose phases take seconds-to-minutes.)
- `/self-iterate start` launches this server in the background and prints `http://localhost:<port>` so
  the user watches the loop run live. Also callable manually on a finished run to browse history.
- **The dashboard is read-only.** It never writes state or drives the loop — the state machine + skill
  do that. Dashboard crashes/lag cannot affect loop guarantees.

Five panels (the user's named requirements + the demo's preserved elements):

| Panel | Source | Content |
|---|---|---|
| Live progress | `state.json` | current phase / round / max_rounds, `met`, phase timeline |
| Results overview | `baseline.json` + `best` + per-round `scores.json` | baseline→best composite, gate pass rates, `met` status, **per-round trajectory chart** (composite / gate / quality) |
| Quality ratings | per-round `quality.json` | per-round quality + rubric dims, guardrail threshold line, regression flag |
| Case comparison | per-round `scores.json` per-case outputs | pick a case → baseline vs chosen round's output, side by side |
| Diff | `winner.diff` + snapshots | per-file, line-level highlighted diff of the harness changes |

Layout: wide multi-panel (demo's preserved layout) — top overview/progress bar, lower region split into
the comparison / chart / diff panels.

**Static archive** — at `done`, also write `report.md` (baseline→best, per-round progression, gate pass
rates, quality, `met`, winning round, maker change summary) and `winner.diff` (`git diff
<baseline_ref>..<best_worktree>` scoped to harness files) into the run dir, for offline/PR use.

## 4. Implementation mapping, tests, scope

**New / changed components:**

- `skills/self-iterate-setup/SKILL.md` (new) — the interactive setup skill (read repo → propose spec →
  confirm → write → call cli `setup`).
- `commands/self-iterate.md` — add `setup` and `start` subcommands; keep `toward` as alias.
- `skills/self-iterate/SKILL.md` — rewrite from "one round only" to "state-machine-driven loop": read
  `state.json`, execute current phase, advance, repeat until `done`.
- `scripts/loop_iter/cli.py` — add `baseline`, `dashboard`, `report`, and a `state`/`advance` helper;
  teach each subcommand to check + advance `state.json` phase; `goal-check` enforces `max_rounds` +
  regression.
- `scripts/loop_iter/state.py` — `RunPaths` → `.self-iterate/runs/<run_id>/`; add `state.json`
  read/write + phase-transition guards + idempotency.
- `scripts/loop_iter/goal_check.py` — quality guardrail + tiebreak; `max_rounds` cap forces `done`.
- `scripts/loop_iter/judge.py` (or a sibling) — quality-judge path (rubric on harness files).
- `scripts/loop_iter/dashboard.py` (new) — stdlib `http.server` watching the run dir; `/api/state`
  merger; serves the SPA from `scripts/loop_iter/dashboard_assets/` (`index.html` + vanilla JS +
  inline-SVG charts, no build step).
- `examples/toy/.self-iterate/toy-basic/` — add `quality.md`; become the template `setup` proposes from.

**Tests (TDD), new + updated:****
- `state.py`: `RunPaths` resolves under `.self-iterate/runs/<id>/`; `state.json` phase transitions
  enforce ordering (refuses out-of-order); idempotent re-run reuses existing phase output; resume from
  `state.json` after a simulated stall.
- `cli.py baseline`: writes `baseline.json` + populates `state.baseline_*`; refuses if `phase != baseline`.
- `cli.py report`: emits `winner.diff` (scoped to harness) + `report.md`; refuses if no rounds.
- `cli.py dashboard`: stdlib server serves `index.html` + `/api/state`; `/api/state` merges
  state+baseline+per-round scores/quality/snapshot; poll returns updated data after a simulated phase
  write; read-only (no state writes from any endpoint); `start` background-launches it and prints the
  URL.
- `goal_check.py`: met = composite ≥ threshold AND no gate regression AND quality ≥
  baseline−tolerance; `round >= max_rounds` & not met → `done` with `met=false`; tiebreak prefers
  higher quality.
- quality-judge: scores harness files per `quality.md`; parallel-with-cases wiring.
- `setup` skill: covered by an integration test that runs the skill against `examples/toy` and asserts
  the generated spec passes `cli.py case-run` (the generated gates/judge actually work).
- Existing 59 tests updated for the `.self-iterate/runs/` path move; stay green.

**Scope (YAGNI):**
- In: `setup` skill; state-machine loop + phase enforcement + resume/idempotency; baseline step;
  quality guardrail + tiebreak; `.self-iterate/runs/` migration; `report` (diff + md); `quality.md`
  template; real-time dashboard (stdlib server + SPA + 5 panels).
- Out (deferred): `/loop` watchdog for walk-away; parallel candidate variants (tournament); early-stop
  on plateau; SSE/streaming dashboard updates (polling first); Windows venv layout; auto-detection of
  `.venv`.

## 5. Risks

- **Continuation is not guaranteed within one session.** The state machine guarantees ordering,
  resumability, and idempotency, but if Claude stalls mid-run the loop pauses until `/self-iterate start`
  is re-invoked (which resumes). True walk-away requires the deferred `/loop` watchdog. This is an
  accepted trade for keeping rich in-session agents.
- **Quality rubric is subjective.** A poorly-written `quality.md` makes the guardrail noisy. `setup`
  must propose a sensible default and the user must review it (D1's confirm step).
- **Generated eval spec quality.** `setup`'s proposed gates/cases are only as good as the repo reading.
  The integration test (generated spec passes `case-run`) is the floor, not a guarantee of a meaningful
  optimization target — the user's confirmation step (D1) is the real gate.
