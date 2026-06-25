# local-service adapter + quality-judge sub-agent — Design

- **Date:** 2026-06-25
- **Status:** Approved (brainstormed across sessions), pending implementation plans
- **Project:** `loop-iteration` (the `self-iterate` plugin)
- **Builds on:** [Plan 1 state machine](2026-06-24-self-iterate-setup-and-loop-design.md), [Plan 2 quality guardrail](2026-06-24-self-iterate-setup-and-loop-design.md) §3.5, [no_overfit programmatic](2026-06-25-no-overfit-programmatic.md), [Plan 4 setup skill](2026-06-25-self-iterate-setup-skill.md)

## 1. Goal & motivation

Two gaps surfaced by dogfooding on `maas-customer-agent` (a locally-run HTTP service on
`localhost:port`):

- **G1 — cases can't run against a variant harness via a running service.** maas is a local HTTP
  service (`/v1/chat`). A *running* service loaded ONE harness at startup; POSTing to it tests that
  fixed harness, not the worktree's variant. The current `python-import` shim sidesteps this by
  rebuilding the agent in-process — but it's a *replica* that must stay in sync with the real service,
  and it doesn't exercise the real HTTP path. For a local service that reads its harness from its
  launch directory, the faithful path is: **per round, start the service FROM the worktree** (so it
  loads the variant harness), POST all cases to it, stop. No current adapter does per-round service
  lifecycle.
- **G2 — the loop can't drive harness-quality (规范度) improvement.** `quality.md` evaluates the
  harness files (clarity/maintainability) but only as a regression guardrail; the maker never sees
  quality dims, so the loop can't proactively trim/dedupe/place. If baseline behavior already passes,
  the loop stops at round 1 with no quality work (the deliberate flip-side of the D5 guardrail
  decision).

This spec closes both: a **`local-service` adapter** (per-round service lifecycle from the worktree)
+ a **`quality-judge` sub-agent** + an opt-in **`quality_target`** mode that feeds quality back to the
maker as an auxiliary optimization target. Both are config/opt-in and fully backward-compatible.

**Part A (local-service) and Part B (quality-judge) are independent subsystems.** This is one design
doc (the user's combined vision) but will be implemented as **two plans** (5a, 5b) for clean
execution and merge.

## 2. Key decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| L1 | **New adapter type `local-service`**: per-round, start the service FROM the worktree (so it reads the variant harness), POST all cases to it, stop at round end. NOT per-case restart. | A running service has a fixed harness; starting it from the worktree per round is the faithful way to test a variant against the real local service. One start/stop per round (not per case) bounds the overhead. |
| L2 | **`local-service` is config-driven** (goal.yaml `agent:`): `start` cmd (with `{worktree}`/`{port}`), `port` (0=auto free port), `ready` URL (poll), `endpoint`, `request` body template (`{query}`), `response_path` (dotted JSON path to answer), `timeout`. | Each local service differs (start cmd, port, request/response shape); config lets one adapter serve all. setup fills the config per-service. |
| L3 | **case_runner gains per-round lifecycle hooks**: `build_run_case` may return a `ServiceAdapter` (`start(worktree)->port`, `run_case(case)->result`, `stop()`); `run_cases` wraps the case loop with start/finally-stop. Per-case adapters (claude-p/command/python-import) are unchanged. | The current `run_cases` is per-case; a service needs per-round setup/teardown. Detecting a ServiceAdapter keeps the gate/judge logic unified. |
| L4 | **New cli `smoke --eval <goal>`**: runs ONE case (case[0]) via the resolved adapter (for local-service: start service from `--base`, POST case[0], stop), prints output + error, no state-machine advancement. Exit 0 if no error. | Setup-time correctness gate: catches a broken entry/adapter config BEFORE `/self-iterate start` burns real calls on all-zero rounds. |
| L5 | **setup skill confirms the entry + writes the config + smoke-tests.** For local-service: ask start cmd / port / ready / endpoint / request+response format (the L2 config), confirm the service reads harness from its launch dir, write goal.yaml `agent:`, run `smoke`, fix until non-error. setup also gains **framework-aware harness** (e.g. maas → only `skills/**` that reach the agent) + a **Loop-mechanics** section so it stops re-deriving from source. | Fills the Plan 4 gap (setup never verified the entry / never wrote the shim / never smoke-tested). |
| Q1 | **New `quality-judge` sub-agent** (agents/quality-judge.md): reads the variant harness + quality.md rubric (+ the programmatic `no_overfit` score as context), returns `{dims, score, maker_feedback}` where `maker_feedback` is specific actionable suggestions (trim/dedupe/place). | A sub-agent gives richer, reasoning-based assessment + actionable maker feedback — exactly what's needed to drive 规范度 improvement. Fits the maker/checker sub-agent pattern (case-evaluator, goal-checker already exist). |
| Q2 | **`quality_target` opt-in** (goal.yaml, optional float). When set: `goal_check.met` requires `quality ≥ quality_target` (in addition to composite≥threshold + no gate regression + no quality regression); the maker receives weak quality dims + `maker_feedback` as auxiliary feedback; the quality-judge sub-agent is dispatched. When unset: current behavior (in-process `judge_quality`, guardrail-only, no feedback, no sub-agent). | Opt-in keeps the D5 guardrail default (no gaming risk, no sub-agent cost) while letting goals that want harness cleanup enable it. Gates stay primary; quality is a secondary target only after gates pass. |
| Q3 | **`no_overfit` stays programmatic (in cli), always.** The quality-judge sub-agent provides the LLM dims (clarity/maintainability) + feedback; `no_overfit` (reliable, cheap) is computed in-process and merged as the floor. | no_overfit is the only reliable quality signal (LLM dims are subjective/flaky); it must not move into the flaky sub-agent. |
| Q4 | **Parallel dispatch**: when `quality_target` enabled, the skill dispatches `case-evaluator` ∥ `quality-judge` per round (realizes the D5-deferred parallelism). | case-eval (output) and quality-judge (harness) are independent per round → run concurrently. |
| Q5 | **Gaming mitigation**: gates remain the primary target and must pass; `quality_target` only drives a second optimization phase once gates pass; `no_overfit` (programmatic) catches hardcoded-answer overfit. The maker is told "keep gates passing AND improve quality toward target." | Prevents the maker from trimming the harness in ways that hurt task performance to score clean. |

## 3. Part A — `local-service` adapter + setup smoke

### 3.1 The adapter (L1, L2, L3)

`agent.type: local-service` in goal.yaml:

```yaml
agent:
  type: local-service
  start: ["bash", "-c", "cd {worktree} && python -m src.server --port {port}"]
  port: 0                      # 0 = auto-pick a free port (bind a socket, pass it in)
  ready: "http://localhost:{port}/health"   # polled until HTTP 200 (or timeout)
  endpoint: "http://localhost:{port}/v1/chat"
  request: '{"query": "{query}"}'           # POST body template; {query} substituted
  response_path: "data.answer"              # dotted path into response JSON -> answer text
  timeout: 120
```

`adapter_generic.py` gains:

```python
class ServiceAdapter:
    """Per-round local-service adapter: start the service from the worktree, POST cases, stop."""
    def __init__(self, config: dict): ...
    def start(self, worktree: str) -> int:
        """Pick a free port (config port=0 -> socket bind), substitute {worktree}/{port} into
        start cmd, Popen it with cwd=worktree, poll `ready` until 200 or timeout. Returns port."""
    def run_case(self, case: dict, worktree: str) -> dict:
        """POST `endpoint` with `request` body ({query} substituted); parse JSON; extract
        response_path; return {case_id, output, trace, error}. Never raises."""
    def stop(self) -> None:
        """Terminate the service subprocess (SIGTERM, then SIGKILL after grace). Never raises."""
```

`build_run_case` returns a `ServiceAdapter` instance when `agent.type == "local-service"` (the
existing per-case callables remain for the other types). `case_runner.run_cases` detects a
`ServiceAdapter` (hasattr `start`/`stop`) and wraps:

```python
def run_cases(cases, worktree, ..., run_case_fn, ...):
    service = run_case_fn if isinstance(run_case_fn, ServiceAdapter) else None
    if service:
        service.start(worktree)
    try:
        for case in cases:
            result = (service.run_case(case, worktree) if service
                      else run_case_fn(case, worktree))
            ... gates + judge (unchanged) ...
    finally:
        if service:
            service.stop()
    ...
```

(Per-case adapters — claude-p/command/python-import — are unchanged: `run_case_fn` is a callable,
`service` is None, the loop behaves exactly as today.)

### 3.2 `smoke` cli (L4)

`cli.py smoke --eval <goal> [--base .]`:
- load goal.yaml + cases[0]; `build_run_case`; if `ServiceAdapter`: `service.start(args.base)` →
  `service.run_case(cases[0], args.base)` → `service.stop()` (try/finally). Else: `run_case_fn(cases[0], args.base)`.
- print `{"case_id", "output", "error"}`; `SystemExit(0 if no error else 1)`.
- No state.json, no phase advance. `--base` is used as the launch dir (for local-service, the
  service starts from the repo — verifying the ENTRY works, not a variant).

### 3.3 setup skill updates (L5)

`skills/self-iterate-setup/SKILL.md` gains:
- **Loop-mechanics section**: worktree = full checkout at baseline; `variant_dir`/launch dir passed to
  the adapter; `harness:` = files the maker edits + snapshot/diff, BUT whether edits reach the agent
  depends on adapter type (claude-p: yes via cwd; local-service: yes via launch-from-worktree;
  python-import: only `skills_dir=variant_dir`, shim-imported prompts are inert). So the skill stops
  re-deriving this from source.
- **Framework-aware harness**: detect the agent framework; propose `harness:` = only files that
  actually reach the agent (e.g. maas zai_adk → `skills/**/*.md`, NOT CLAUDE.md/AGENTS.md which it
  doesn't read).
- **Entry confirmation for `local-service`**: ask the start cmd, port, ready endpoint, `/v1/chat`
  endpoint, request body + response_path; CONFIRM the service reads harness from its launch dir (if
  not, local-service won't work — fall back to python-import shim). Write the `agent:` config.
- **Smoke gate**: after writing the spec, run `cli.py smoke --eval <goal>`; if error, fix the config
  (or start cmd) and re-run until non-error. Only then declare setup done.

## 4. Part B — `quality-judge` sub-agent + `quality_target`

### 4.1 The `quality-judge` agent (Q1)

`agents/quality-judge.md` — a checker sub-agent. Given the worktree, the harness file paths, the
`quality.md` rubric, and the programmatic `no_overfit` score (passed as context), it:
- reads the variant harness files,
- reasons about the LLM dims in `quality.md` (clarity, maintainability — NOT no_overfit, which is
  already computed),
- returns strict JSON: `{"dims": [{"dim": "clarity", "score": 8.0}, ...], "score": 8.0,
  "maker_feedback": "<specific, actionable suggestions: trim X, dedupe Y, place Z>"}`.
- `maker_feedback` is the key addition: concrete guidance the maker can act on (not just a score).

### 4.2 `quality_target` opt-in (Q2)

`goal.yaml` optional `quality_target: 8.0`. Semantics:
- **Disabled (unset)**: current Plan-2 behavior. `case-run` computes quality in-process
  (`judge_quality` LLM dims + `no_overfit`), guardrail-only, no sub-agent, no maker feedback. Cheap.
- **Enabled**: `case-run` computes ONLY `no_overfit` (programmatic; skips the in-process
  `judge_quality` LLM dims — the sub-agent will provide them) and writes a preliminary `quality.json`
  (no_overfit only). The skill dispatches `quality-judge` ∥ `case-evaluator`; after the sub-agent
  returns, the skill calls a new cli `quality-merge --eval <goal> --run-id <id> --round <N>` with the
  sub-agent's `{dims, score, maker_feedback}` on stdin, which **merges** `no_overfit` (from case-run)
  + the sub-agent's LLM dims + `maker_feedback` into `quality.json` and updates the round's `quality`
  in `scores.json`. (cli owns state; the skill orchestrates — it does not write scores.json by hand.)
  `goal_check.met` then requires `quality ≥ quality_target` (on top of composite + no gate regression
  + no quality regression). The maker receives: failing gates + weak output-judge dims + **weak
  quality dims + `maker_feedback`** (auxiliary). When gates already pass but `quality <
  quality_target`, the maker's job shifts to harness cleanup per the feedback (Q5 two-phase).

### 4.3 Parallel dispatch (Q4)

The `self-iterate` skill, in the eval phase (when `quality_target` enabled), dispatches
`case-evaluator` and `quality-judge` **concurrently** (two Agent calls in one message), then merges.
When disabled, eval is the current single `case-run` (no sub-agent). This realizes the D5-deferred
parallelism, gated on `quality_target` to avoid the sub-agent cost when not optimizing quality.

### 4.4 no_overfit floor (Q3)

`no_overfit_score` (programmatic, `quality_prog.py`) is computed in `case-run` always (it's cheap,
reliable, and the floor that catches hardcoded-answer overfit regardless of LLM flakiness). It is
merged into `quality` in both modes. The `quality-judge` sub-agent receives it as context (so it
doesn't re-judge it) and the orchestrator ensures the programmatic value wins for the `no_overfit`
dim (same override as today's `_compute_quality`).

## 5. Implementation mapping, tests, scope

**Part A (plan 5a):**
- `scripts/loop_iter/adapter_generic.py` — `ServiceAdapter` + `build_run_case` returns it for
  `local-service`; `_KNOWN_TYPES` adds `local-service`.
- `scripts/loop_iter/case_runner.py` — `run_cases` wraps the loop with `start`/`finally stop` for a
  `ServiceAdapter`.
- `scripts/loop_iter/cli.py` — `smoke` subcommand.
- `scripts/loop_iter/validate_spec.py` — validate `local-service` config (start/endpoint/request
  required; warn if no ready check).
- `skills/self-iterate-setup/SKILL.md` — Loop-mechanics + framework-aware harness + local-service
  entry confirmation + smoke gate.
- `tests/test_adapter_generic.py` / `tests/test_case_runner.py` / `tests/test_cli.py` — ServiceAdapter
  (start/run_case/stop with stubbed subprocess+httpx; port auto-pick; ready-poll; stop-never-raises),
  run_cases wraps ServiceAdapter (start once, all cases, stop in finally), smoke cli (1 case, no
  state, exit code).
- `examples/` — a `local-service` example goal (a tiny local HTTP service + spec) for an integration
  test.

**Part B (plan 5b):**
- `agents/quality-judge.md` — new sub-agent.
- `scripts/loop_iter/goal_check.py` — `check_and_advance` / `check_latest`: when `quality_target`
  set, `met` requires `quality ≥ quality_target` (and the existing no-regression).
- `scripts/loop_iter/cli.py` — `_case_run`: when `quality_target` set, compute only `no_overfit`
  (skip in-process `judge_quality`); else current `_compute_quality`. Plus a new `quality-merge`
  subcommand (merges sub-agent dims + no_overfit into quality.json + the round's quality in
  scores.json).
- `skills/self-iterate/SKILL.md` — when `quality_target` set: dispatch case-evaluator ∥
  quality-judge; merge; pass quality dims + `maker_feedback` to the maker; two-phase framing.
- `tests/test_goal_check.py` / `tests/test_cli.py` — `quality_target` met requirement; case-run
  skips judge_quality when target set; merge logic.
- (The quality-judge agent itself is LLM behavior — covered by dogfooding, like the other agents.)

**Scope (YAGNI):**
- In: `local-service` adapter + lifecycle + smoke; setup entry/smoke/framework-aware-harness/Loop-
  mechanics; `quality-judge` agent; `quality_target` opt-in (goal_check + case-run + skill parallel +
  maker feedback); no_overfit stays programmatic.
- Out (deferred): auto-detection of the service's request/response format (setup asks the user);
  remote/deployed services (local only — you control the machine); service log capture beyond
  stderr; concurrent rounds (still sequential — one service at a time).

## 6. Risks

- **Service lifecycle flakiness**: start/stop per round adds failure surfaces (port conflicts, slow
  startup, zombie processes). Mitigation: `stop` is best-effort (SIGTERM→SIGKILL), port auto-pick
  avoids conflicts, `ready` poll with timeout fails fast, `smoke` catches config errors at setup.
- **Config brittleness**: `request`/`response_path` templates vary per service; a wrong template =
  all-zero rounds. Mitigation: `smoke` at setup verifies one case end-to-end before declaring done.
- **Sub-agent cost**: `quality-judge` per round (when `quality_target` enabled) adds a full agent
  invocation. Mitigation: opt-in (disabled = no sub-agent); parallel with case-eval amortizes wall-
  clock.
- **Quality-judge flakiness**: LLM dims (clarity/maintainability) are subjective; the sub-agent may
  vary. Mitigation: `no_overfit` (programmatic) is the reliable floor; LLM dims degrade to absent
  (quality still has no_overfit). `maker_feedback` is advisory (maker still must keep gates passing).
- **Gaming**: maker could trim the harness to look clean while hurting generalization. Mitigation:
  gates primary (must pass); `no_overfit` catches hardcoding; `quality_target` only phases in after
  gates pass.
