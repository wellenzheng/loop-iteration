# Self-Iteration Loop — Design

- **Date:** 2026-06-23
- **Status:** Approved (brainstormed), pending implementation plan
- **Project:** `loop-iteration`
- **Governing doctrine:** [`.claude/skills/loop-engineering/SKILL.md`](../../../.claude/skills/loop-engineering/SKILL.md)

## 1. Goal

A loop, driven from inside Claude Code, that **self-iterates any agent's *harness*** — its
prompt, skills, and tools — until a **user-defined, verifiable goal** is met. The loop is
expressed entirely in loop-engineering primitives: a skill that defines one round, sub-agents
that make and check, worktrees that isolate each candidate, on-disk state that survives
between runs, and a run-until-done driver whose separate reviewer judges the stop condition.

This is a **generalized reimplementation** of
`~/Desktop/Self-iteration-demo/fast-self-iterating-agent-mvp`, rebuilt loop-engineering-native
and minimal, so different users can point it at different agents with their own goals and
evaluation criteria, in their own dev workspace.

## 2. Prior-art analysis (`fast-self-iterating-agent-mvp`)

**What it does (the closed loop we keep):** baseline QA → business eval (before) → skill
quality eval + skill rewrite loop (→ A-grade) → backtest with optimized skills → business eval
(after) → compare (mean / bad-case delta).

**The one idea to carry forward — backend selection:** `run_loop.py` *only orchestrates*; the
eval and rewrite logic lives in Claude Code Skills. Knowledge stays in skills, not in code.

**What to drop / generalize:**
- `maas_adapter_local.py` imports `src.agent` and **monkey-patches `_SKILLS_DIR`** to redirect
  skills — the core thing that makes it non-general. Replaced by a clean adapter seam + git
  worktree variant isolation (no global state).
- Customer-support-specific rubric (F1–F6, 9 dims) — generalized into a user-authored eval spec.
- Coupling to the MaaS service and `skills_override`/`write_back_to_maas` — replaced by worktree
  overlay + optional merge.

**Engineering debt to avoid (from `REVIEW.md`):** the 3483-line god-module `run_loop.py`;
zero tests; hand-rolled JSON repair (`_fix_unescaped_quotes`); monkey-patch concurrency hazard;
config side-effects from CLI flags. We avoid all of these by design (small focused units,
structured output, no global state, tests from day one).

## 3. Key decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Native core + thin adapter seam** | Agents under test are first Claude Code skills/prompt/tools configs (loop iterates real files, hermetic). `run-one-case / apply-variant` go through a small interface so external agents plug in later without redesign. |
| D2 | **Composite eval: programmatic gates + LLM-judge dims** | Gates give a verifiable stop condition (loop-engineering core); judge dims handle open-ended quality (what the demo's rubric did). Weighted composite per goal. |
| D3 | **Toy agent first; maas = adapter #2** | A tiny in-repo agent + small QA set + simple rubric proves the loop end-to-end hermetically (no service/keys). maas validates the generalization later. |
| D4 | **Skill-driven loop + run-until-done** | A `self-iterate` skill defines one round (maker → checker → state); `ralph`/`autopilot` repeats until the verifiable goal holds, with a **separate reviewer** checking the stop condition. Most loop-engineering-native, minimal, no orchestration script to maintain. |

## 4. Design

### 4.1 Core concept & the three seams

All generalization lives behind **three seams**. Everything else is generic across agents.

```
                        ┌─────────────────────────────────────────────┐
   user provides ──────▶│  ADAPTER   (per agent)                      │
                        │   apply_variant(harness_files) -> worktree  │  stage a candidate harness
                        │   run_case(case, worktree) -> result+trace  │  invoke THAT agent on one case
                        └─────────────────────────────────────────────┘
                        ┌─────────────────────────────────────────────┐
   user provides ──────▶│  EVAL SPEC (per goal)                        │
                        │   cases.json  · gates.* (programmatic)       │  verifiable, authoritative
                        │   judge.md (LLM rubric) · weights · threshold│  open-ended quality
                        │   max_rounds · regression policy             │
                        └─────────────────────────────────────────────┘
   the loop rewrites ──▶│  VARIANT  (per round)                        │
                        │   the agent's harness files (prompt/skills/  │  what the maker mutates
                        │   tools), staged in a git worktree           │
                        └─────────────────────────────────────────────┘
```

- **Adapter** = the only agent-specific part (how to run it). v1 = `adapters/toy/`; maas = adapter
  #2, only `run_case` differs (call the MaaS service instead of a Claude session).
- **Variant + worktree** = the exact mechanism that replaces the demo's `skills_override` /
  `write_back_to_maas`: each candidate harness is staged as a **git worktree**, so source is never
  mutated mid-loop. The user merges the winning worktree when satisfied. Same for Claude-native and
  maas, unchanged.
- **Eval spec** = the "user customizes goal + criteria" requirement.

**Eval model (explicit — removes ambiguity for the goal-checker):**
- **Gates** = programmatic, binary per case (pass/fail). They feed the composite as a **weighted
  pass-rate** across cases, and are *separately* subject to the regression check. They are the
  verifiable spine.
- **Judge dims** = LLM-scored (e.g. 0–10), open-ended quality. Each feeds the composite as a
  weighted mean across cases.
- **Composite score** = single number = weighted combination of (gate pass-rate) + (each judge dim
  mean). Weights in `goal.yaml`. One number, by design — simplest thing the goal-checker compares.
- **Goal met** = `composite ≥ threshold` AND `no gate-regression vs best-so-far` AND
  `rounds ≤ max_rounds`. (Gates are not a separate hard "all-must-pass" floor in the minimal
  version; their pass-rate is in the composite and a gate getting *worse* trips the regression
  guard even if the composite rose. A future `hard: true` gate flag is a non-goal for v1.)

**What gets iterated:** the harness — the files the agent loads (`SKILL.md`/prompt/tools defs).
Not the agent's source code, not its model. This matches the demo (iterating the skill package) and
the stated "prompt、skills、tools".

### 4.2 Components (units — each one clear purpose)

| Unit | Does | Used by | Depends on |
|---|---|---|---|
| **`self-iterate` skill** (`.claude/skills/self-iterate/SKILL.md`) | Defines *one round*: read state → maker → checker → write state → report goal-met? | invoked on "self-iterate `<agent>` toward `<goal>`"; wrapped by run-until-done | adapter, eval spec, state, maker/checker |
| **`harness-rewriter` sub-agent** (maker) | Rewrites the variant's harness files in the worktree, guided by last round's failing gates/dims as *themes* (not per-case patches — carries the demo's good `_build_business_rewrite_brief` idea) | dispatched once per round by the skill | current variant worktree, last round's eval findings |
| **`case-evaluator` skill/sub-agent** (checker) | Runs all cases through the adapter → applies eval spec (gates + judge dims) → composite score. Returns per-case + aggregate + failing items + regression flags | dispatched by the skill after the maker | adapter (`run_case`), eval spec (`gates`/`judge.md`) |
| **`goal-checker` sub-agent** (separate reviewer) | Reads latest scores + state, judges whether the *verifiable goal* is met (composite ≥ threshold AND no gate regression AND ≤ max_rounds). **Independent agent, not the maker.** | run-until-done's stop-condition judge | `scores.json`, `goal.yaml` |

This maps directly onto loop-engineering: **skill** = knowledge, **sub-agents** = maker/checker
split, **worktree** = variant isolation, **on-disk state** = memory, **goal-checker** = the stop
condition judged by an agent different from the maker (the `/goal` maker/checker split).

The checker evaluates each round's variant; the goal-checker evaluates the *stop condition*. The
separation is applied at both layers.

### 4.3 One-round data flow + the loop driver

```
self-iterate (one round):
  1. read  .loop/iterate/<run_id>/progress.md  +  last scores
  2. open  a worktree from the baseline agent, overlay the current variant
  3. maker:   rewrite harness files in the worktree, guided by last round's
              failing gates/dims (themes, not per-case patches)
  4. checker: for each case → adapter.run_case(case, worktree) → result
              → eval gates (programmatic) + judge dims (LLM) → per-case scores
              → composite score; regression check vs best-so-far
  5. write   scores.json (round N); snapshot variant/round_N/; update progress.md
  6. report  goal met?  ── no ──▶ run-until-done fires the next round
                │
                └─ yes (or hit max_rounds) ──▶ stop; best variant surfaced
```

The **loop itself** = `ralph`/`autopilot` (run-until-done). It keeps invoking `self-iterate` until
`goal-checker` reports the verifiable condition holds — no orchestration code written, exactly the
"design the loop, not a pile of bash to maintain" shape. A user may also run a single round
manually for interactive control.

### 4.4 State layout

```
loop-iteration/
├── adapters/
│   ├── toy/                                     ← adapter #1 (ships in minimal version)
│   │   ├── run_case.py                          ← run_case(case, worktree) -> result
│   │   ├── apply_variant.py                     ← apply_variant(files) -> worktree
│   │   └── agent_files/                         ← toy agent's baseline harness
│   │       ├── SKILL.md   prompt.md   tools.json
│   └── maas/        (adapter #2 — later; only run_case differs)
├── evals/
│   └── toy-basic/                               ← a goal: the toy agent's eval spec
│       ├── goal.yaml     # threshold, max_rounds, weights, regression policy
│       ├── cases.json    # the QA set
│       ├── gates.py      # programmatic checks on each result (verifiable)
│       └── judge.md      # LLM rubric (open-ended dims)
├── .claude/skills/
│   ├── loop-engineering/   (doctrine — exists)
│   ├── self-iterate/       (one round)
│   └── case-evaluator/     (checker)
├── .claude/agents/
│   ├── harness-rewriter.md (maker)
│   └── goal-checker.md     (run-until-done reviewer)
└── .loop/
    ├── progress.md                               ← project spine (exists from bootstrap)
    └── iterate/<run_id>/                         ← one self-iteration run
        ├── progress.md      # human-readable: round N, best score, what's tried
        ├── scores.json      # per-round composite + per-case scores + regressions
        ├── goal-met.json    # the goal-checker's verdict (stop-condition record)
        ├── variants/round_N/  # snapshot of each candidate harness
        └── report.md        # final before/after comparison
```

`run_id` = `YYYYMMDD_HHMMSS_<8hex>` (same stamp style as the demo). Only `.loop/iterate/<run_id>/`
is authoritative; intermediate worktrees are cleaned up. This gives the demo's provenance
(baseline/optimized snapshots, per-run archive, no history overwrite) without the 3400-line
generator.

### 4.5 How a user runs it in their workspace

```
1. ADAPTER  — put their agent behind the seam:
     adapters/<my-agent>/{run_case, apply_variant, agent_files/}
2. GOAL     — write their loop goal + eval criteria:
     evals/<my-goal>/{goal.yaml, cases.json, gates.*, judge.md}
3. RUN      — in Claude Code, in their workspace:
     "self-iterate <my-agent> toward <my-goal>"
     → run-until-done drives rounds; watch .loop/iterate/<run_id>/progress.md
4. DECIDE   — when goal-checker says met (or cap hit), review report.md;
     merge the winning variant worktree into their agent's repo. The loop
     never auto-merges — the human stays the engineer.
```

Customization points: **loop goal** = `goal.yaml` (threshold + max_rounds + regression policy);
**eval criteria** = `gates.*` + `judge.md` (weights per goal); runs in **their own dev workspace**
(they drop adapter + eval into their repo and run it from Claude Code).

### 4.6 Error handling

- **`run_case` failure** (agent crash/timeout) → that case scores 0 on gates, flagged `error`;
  never crashes the round. A flaky adapter fails a case, not the loop.
- **LLM-judge parse failure** → retry once with a strict-output prompt; if still failing, fall back
  to *gates-only* score for that case and log. **No hand-rolled JSON-repair state machine** (the
  demo's `_fix_unescaped_quotes`) — use structured/strict output and degrade gracefully.
- **Regression policy** (configurable, default `block`): a candidate that regresses on **any** gate
  vs best-so-far is *not* promoted — kept as a `variants/round_N/` snapshot, and the regression is
  fed back to next round's maker. Per-goal policy `block | allow`.
- **Always capped:** `max_rounds` always terminates. If we hit the cap, goal-checker reports "not
  met, hit cap" with the best variant found. "Done" is a verifiable claim, not a vibe.
- **Worktree cleanup:** variant worktrees are torn down at end of round (or on crash); only
  snapshots persist. No demo-style `_PATCHED_SKILLS_DIR_ORIG` stuck-patched-after-death — there is
  no global state, only worktrees that get discarded.

### 4.7 Testing

- **Adapter contract:** `apply_variant` is hermetic (source repo never touched mid-loop — assert
  byte-identical); `run_case` returns the agreed shape on the toy agent.
- **Eval machinery:** gates return deterministic pass/fail on fixtures; the judge prompt yields
  parseable structured output; **composite scoring is a pure function → unit-tested** (weights,
  threshold, regression detection).
- **goal-checker logic:** the stop condition (threshold AND no regression AND ≤ max_rounds) is a
  **pure function → unit-tested**, including boundaries (exactly-at-threshold, gate-regression,
  cap-hit).
- **Golden round (integration):** seed a deliberately-broken toy harness + a case a known fix passes
  → assert the loop *raises* the composite and does not regress. Proves the whole maker→checker→goal
  chain on one knowable case.
- **No god-module:** every unit is a focused file (skill / sub-agent / adapter / eval), so tests
  target precisely and Claude can hold each unit in context at once.

## 5. Scope (minimal version — YAGNI)

**In:** 1 adapter (`toy`), 1 eval shape (gates + judge), `self-iterate` skill, maker + checker +
goal-checker, worktree variant isolation, on-disk state, run-until-done driver, basic tests.

**Out (explicitly, for later):** web UI, FastAPI server, the `maas` adapter (#2), backtest via a
running service, auto-merge / PR connectors, multiple concurrent goals.

## 6. Open questions / future

- **maas adapter #2:** only `run_case` differs (invoke the MaaS service); `apply_variant` reuses the
  worktree-overlay mechanism. Validates the generalization claim.
- **Parallel per-case eval:** if case counts grow, the checker can fan out cases across parallel
  sub-agents (or a workflow stage) — deferred until the toy loop is proven.
- **Connectors (block 4 of the doctrine):** when a user wants the loop to open a PR / update a ticket
  itself, wire an MCP connector at the DECIDE step; not needed for minimal.
