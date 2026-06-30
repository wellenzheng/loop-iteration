# Latency as an Optimization Metric — Design Spec

**Date:** 2026-06-30
**Status:** Approved (design), pending implementation plan
**Approach:** B (phased) — universal wall-clock scoring + standardized best-effort internal `trace.timings`

## Goal

Make agent runtime a first-class optimization target in the self-iterate loop: the maker is
driven to reduce per-case latency, with internal-call-timing visibility (best-effort per adapter
type) to guide its edits. Works across all 5 adapter types.

## Decisions (from brainstorming)

- **Role:** optimization target (drive faster), not just a regression guard.
- **Scope:** all adapter types (python-import, claude-p, local-service, command/custom).
- **Target definition:** relative to baseline (`latency_score = baseline_mean / round_mean`).
- **Reward shape:** uncapped (`latency_score` may exceed 1.0 → composite may exceed 1.0). Containment
  of "do-less-to-go-fast" gaming relies on gates + judge dims, NOT a cap.
- **Internal timings:** best-effort visibility only — they do NOT enter the score. The scored signal
  is the universal per-case `elapsed_ms` (wall-clock of `run_case` only).

## Architecture & Data Flow

```
per case (_run_one):
  t0 = perf_counter()
  result = run_case(case, worktree)            # ONLY agent execution timed
  elapsed_ms = (perf_counter() - t0) * 1000     # try/finally: recorded even on exception
  → case_score["elapsed_ms"] = elapsed_ms
  → case_score["trace"]["timings"] = [...]      # best-effort, filled by adapter

per round (case_run):
  round_latency_ms = mean(case.elapsed_ms)      # universal, all types
  baseline_latency_ms = baseline.json["round_latency_ms"]
  latency_score = compute_latency_score(round_latency_ms, baseline_latency_ms)  # uncapped; baseline round = 1.0
  if "latency" in weights:
      composite = composite(case_scores, weights, extra={"latency": latency_score})  # may be >1.0
  → scores.json round gets: round_latency_ms, baseline_latency_ms, latency_score, per-case elapsed_ms + trace.timings

maker feedback:
  if trace.timings present → attribute to phase ("kb_search 1→2 calls +340ms; llm_call 820→1100ms")
  else → degrade to per-case elapsed delta ("c5: 1.2s vs baseline 0.9s")
```

**Key invariants:**
1. Only `run_case` is timed — gates/judge are eval overhead, not agent time; mixing them pollutes the signal.
2. The scored signal is universal wall-clock (per-case `elapsed_ms` → round mean); works for all 5 types immediately.
3. `latency_score` depends on the baseline, which `run_cases` does not have. `run_cases` produces
   `round_latency_ms` only; the **cli (`_case_run`)** reads baseline, computes `latency_score`, and
   overlays it onto `composite`. This keeps `run_cases`' composite behavior identical to today when
   `weights.latency` is absent (zero change to existing tests).
4. composite may exceed 1.0; `goal_met` (`comp >= threshold`) still holds. Gaming is contained by
   gates (correct_skill, no_wrong_route — empty/wrong output fails) + judge dims (quality drop
   lowers composite), NOT by a cap.
5. Internal `trace.timings` is best-effort visibility, never scored. Missing timings → attribution
   degrades to per-case deltas, never crashes.

## Components & File Changes

### `scripts/loop_iter/case_runner.py`
- `_run_one`: wrap `run_case` (or `service.run_case`) with `time.perf_counter()` in try/finally so
  `elapsed_ms` is recorded even when `run_case` raises. Write `elapsed_ms` into the case score.
- `run_cases` return dict gains `round_latency_ms` (= `mean(elapsed_ms)`, 0 for empty cases).
- composite is still computed the old way (gates+judge, no latency) — unchanged behavior.
- `trace.timings` is filled by the adapter into `result["trace"]`; case_runner passes `trace` through
  unchanged (already does).

### `scripts/loop_iter/scoring.py`
- `composite(case_scores, weights, extra=None)`: new optional `extra: dict[str, float]` (component
  name → score, may be >1). When present, folded in with `weights[name]`; absent → current behavior.
  `latency_score` is passed as `extra={"latency": ...}`.
- New `compute_latency_score(round_latency_ms, baseline_latency_ms) -> float`: baseline 0/None → `1.0`
  (neutral, degrade); `round_latency_ms == 0` → `1.0` (avoid divide-by-zero); else
  `baseline / round` (uncapped). (Named `compute_latency_score`, not `latency_score`, to avoid
  collision with the `latency_score` field stored in the round.)
- `goal_met` unchanged (`comp >= threshold` still valid with composite >1.0 possible).

### `scripts/loop_iter/cli.py`
- `_case_run`: after `run_cases`, if `"latency" in weights` → read baseline `round_latency_ms` from
  `baseline.json`, compute `latency_score`, set
  `out["composite"] = composite(case_scores, weights, extra={"latency": ls})`; write
  `round_latency_ms` / `baseline_latency_ms` / `latency_score` into the round.
- `_baseline`: `latency_score = 1.0` (no prior baseline); `baseline.json` stores `round_latency_ms`
  for later rounds to reference.
- Reading baseline latency: from `baseline.json` (already loaded); old baseline.json without the
  field → None → `latency_score = 1.0` (graceful).

### `scripts/loop_iter/latency_feedback.py` (new, single-responsibility)
- `latency_feedback(round_cases, baseline_cases) -> str` — pure function:
  1. timings present (python-import): aggregate per-phase ms+count for round vs baseline; list the
     top-3 phases by ms increase ("kb_search: 1→2 calls, +340ms; llm_call: 820→1100ms").
  2. timings absent (command/custom etc.): degrade to per-case elapsed delta; list top-3 slowest
     cases ("c5: 1.2s vs baseline 0.9s").
  3. baseline_cases missing timings or absent: report round's own top phases/cases only, no diff.
- Output joins the maker input via the same channel as existing quality `maker_feedback` (round
  fields in scores.json + SKILL.md guidance to read them).

### `scripts/loop_iter/validate_spec.py`
- `weights` already validated as a non-empty dict. New: if `weights.latency` present, emit a warning:
  "latency is uncapped; composite may exceed 1.0; rely on gates+judge to contain do-less-to-go-fast
  gaming — keep weights.latency small."

### maas `entry.py` (python-import shim — the only adapter change in phase 1)
- In `_run`, timestamp `ToolCallEvent` capture points with `time.perf_counter()`; write
  `trace["timings"] = [{"phase": "tool_call:<name>", "ms": ..., "count": ...}, {"phase": "llm_call", "ms": ..., "count": ...}]`.
- LLM-call ms approximated as the non-tool spans of `query_stream` (time between events not inside a
  tool call). Good enough for phase 1.
- Tooling points wrapped in try/except so a timing failure never affects agent execution.

### Docs: `skills/self-iterate-setup/SKILL.md`, `skills/self-iterate/SKILL.md`, `README.md`
- Document `weights.latency` (opt-in, relative-to-baseline, uncapped) and the `trace.timings` schema.

### Phase 2 (out of scope for this spec — future work)
- claude-p: `run_case_default` switches to `--output-format stream-json`, parses event timestamps →
  per-phase timings.
- local-service: `ServiceAdapter` extracts a `timing` path from the response JSON (like `response_path`).

## `trace.timings` Schema

```python
result["trace"]["timings"] = [
  {"phase": "llm_call",                "ms": 820.3, "count": 1},
  {"phase": "tool_call:kb_search",     "ms": 340.1, "count": 1},
  {"phase": "tool_call:read_reference","ms":  12.4, "count": 1},
]
```

- `phase`: `llm_call` or `tool_call:<tool_name>` (aligned with existing `trace.tool_calls[].tool`).
- `ms`: cumulative ms for that phase; `count`: occurrences (same phase repeated → ms summed, count+1).
- **Not a mandatory contract**: adapters fill what they can; absence of the `timings` key is fine.
  Plugin checks existence before reading.

Adapter fill capability:

| adapter | phase 1 | source |
|---|---|---|
| python-import | yes | maas shim timestamps ToolCallEvent; llm_call = non-tool spans |
| claude-p | no (phase 2) | stream-json event timestamps |
| local-service | no (phase 2) | response JSON timing field |
| command/custom | no | only total elapsed_ms, no timings |

## goal.yaml Configuration

```yaml
weights:
  gates: 0.5
  routing_fidelity: 0.3
  answer_coherence: 0.1
  latency: 0.1            # NEW, opt-in. relative to baseline, uncapped
```

- Single new knob: `weights.latency`. No `latency_budget`, no `latency_agg`, no `latency_tolerance`
  (YAGNI — relative-to-baseline + uncapped already implies regression penalty; no separate guard).
- Aggregation fixed to mean (no config exposed).
- `composite()` normalizes by total weight (divides by `w_total`), so adding `latency` does not
  require re-tuning other weights — add 0.1 and the rest auto-scales.

## composite >1.0 Semantics & Containment

- `latency_score = baseline_mean / round_mean`, uncapped → round 2x faster than baseline gives 2.0 →
  composite may exceed 1.0.
- `goal_met`: `comp >= threshold` still holds (threshold stays 0-1, e.g. 0.85). composite >1.0 just
  means "exceeded"; does not change the verdict logic.
- **Containment of gaming** (maker doing less to go fast → empty output / skipped tools → huge
  latency_score):
  - gates (`correct_skill`, `no_wrong_route`): empty/wrong output fails the gate → gate-regression
    blocks `met`.
  - judge dims (routing_fidelity etc.): quality drop lowers composite.
  - Net: "to gain latency score you must keep gates+judge." A small `weights.latency` (0.1) means
    latency alone cannot push composite past threshold.
- No cap (per the uncapped decision); the containment dependency is stated explicitly in the
  validate_spec warning so users keep `weights.latency` modest.

## Error Handling (all degrade, never crash a round)

| Situation | Behavior |
|---|---|
| baseline.json has no `round_latency_ms` (old baseline / first run) | `latency_score = 1.0` (neutral) |
| `round_latency_ms == 0` (all cases instant, theoretical) | `latency_score = 1.0` (avoid divide-by-zero) |
| `run_case` raises | `elapsed_ms` still recorded (perf_counter in finally); `error` field as usual; actual elapsed counted in round mean |
| `trace.timings` absent | attribution degrades to per-case delta, no crash |
| `weights.latency` absent | latency branch skipped entirely; composite as today |
| maas shim timing fails | timings not written; trace still returns normally (timing wrapped in try/except) |

## scores.json / baseline.json Field Additions

Round fields (new): `round_latency_ms`, `baseline_latency_ms`, `latency_score`.
Case fields (new): `elapsed_ms`. `trace.timings` lives inside the existing `trace` field.
All additive; old fields unchanged.

## Testing Strategy

### `tests/test_scoring.py` (new)
- `composite()` with `extra={"latency": ls}`: folds in by weight, may exceed 1.0; without `extra`
  behaves as today (regression guard).
- `compute_latency_score()`: normal ratio; baseline=0 → 1.0; baseline=None → 1.0; round=0 → 1.0
  (divide-by-zero guard); round 2x faster → 2.0 (uncapped); round 2x slower → 0.5.

### `tests/test_case_runner.py` (new)
- `elapsed_ms` recorded per case: stub `run_case` with `time.sleep(0.05)`, assert `elapsed_ms >= 40`.
- `elapsed_ms` covers run_case only, not gates/judge: run_case/gates/judge stubs all sleep; assert
  elapsed_ms ≈ run_case portion only.
- `elapsed_ms` recorded even when run_case raises (finally).
- `round_latency_ms` = mean(elapsed_ms); empty cases → 0.
- Parallel path (parallelism>1) records elapsed_ms correctly.

### `tests/test_cli.py` (new)
- `weights.latency` present: case_run reads baseline round_latency_ms → computes latency_score →
  composite overlaid (may be >1.0); round fields include `round_latency_ms`/`baseline_latency_ms`/`latency_score`.
- `weights.latency` absent: composite as today; round has no latency fields (regression guard).
- baseline path: latency_score=1.0; baseline.json contains round_latency_ms.
- old baseline.json (no round_latency_ms): latency_score=1.0, no crash.

### `tests/test_latency_feedback.py` (new, pure function)
- timings present: round vs baseline, per-phase aggregation, top-3 phases by ms increase (with count delta).
- timings absent: degrades to per-case delta, top-3 slowest cases.
- baseline missing timings: reports round's own top only, no crash.
- empty input / missing fields: returns empty string or friendly note, no raise.

### `tests/test_validate_spec.py` (new)
- `weights.latency` present → warning about composite >1.0 + containment dependency.
- existing weights validation unaffected.

### maas side (manual smoke, not a unit test)
- After `entry.py` change: run a 6-case smoke at `parallelism=1`; confirm `trace.timings` populated
  and agent behavior unchanged (gates still pass).
- Run one round vs baseline; confirm `latency_score` is sensible.
