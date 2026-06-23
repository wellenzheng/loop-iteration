# Progress — loop-iteration

> **This is the on-disk state spine.** It lives on disk, not in any conversation, so a
> fresh session/loop can pick up where the last one stopped. **Every meaningful run:
> read this first, write to it before stopping.** (loop-engineering doctrine: the agent
> forgets; the repo doesn't.)

## Current goal
Bootstrap the loop-iteration project as a loop-first codebase.

## Stopping condition (verifiable — "done" is a command, not an opinion)
```
git rev-parse --is-inside-work-tree \
  && test -f .loop/progress.md \
  && test -f README.md \
  && grep -q "Automations" README.md && grep -q "Worktrees" README.md \
  && grep -q "Skills" README.md && grep -q "Connectors" README.md \
  && grep -q "Sub-agents" README.md && echo BOOTSTRAP_OK
```
Status: **MET** (run by the maker on 2026-06-23; human to re-run as checker).

## Done
- 2026-06-23 — Doctrine skill installed at `.claude/skills/loop-engineering/SKILL.md`.
- 2026-06-23 — `git init`; `.gitignore` added (excludes the eval scratch workspace).
- 2026-06-23 — This state spine created.
- 2026-06-23 — `README.md` playbook written (maps all 5 blocks to concrete handles).
- 2026-06-23 — **Self-iteration loop minimal version implemented** (16-task plan, branch
  `feat/self-iteration-loop`). Python core: `scoring`, `gates`, `judge`, `adapter`,
  `case_runner`, `goal_check`, `state`, `llm_client`. Toy adapter + `toy-basic` eval.
  Skills: `self-iterate`, `case-evaluator`. Sub-agents: `harness-rewriter` (maker),
  `goal-checker` (reviewer). **30 tests green.** Golden-round integration proves the
  machinery (score rises, goal met, regression blocked).
- 2026-06-23 — **Live checks (no-secret) PASS:** `goal_check` CLI prints verdict + exits
  1 on not-met (by design); `apply_variant` creates a real worktree of this repo, source
  stays byte-identical after a worktree edit (hermetic), cleans up.

## In flight
- **Live end-to-end round PENDING user environment** — a full `case_runner` round needs the
  real `claude` CLI in the worktree + `OPENAI_API_KEY` for the judge. Not runnable in the
  build session (no secrets). This is the remaining manual gate before declaring the loop
  production-usable.

## Blocked
- **No connectors wired (block 4)** — by design. Wire on the first loop that needs to
  *act* in the environment (open a PR, update a ticket, ping a channel). Wiring one now
  would be intent debt — we don't yet know which env this project ships into.
- **No product decided** — `src/` / app skeleton deliberately not created. Picking the
  product is the first *real* loop, not a bootstrap decision.

## Next
The first real loop goal is now concrete: **dogfood the loop on the toy agent.**
`- [ ] self-iterate toy toward toy-basic — done when: a live run raises the composite to ≥0.85
   threshold with no gate regression (run with OPENAI_API_KEY + the claude CLI available), and
   `python -m loop_iter.goal_check --eval evals/toy-basic --run-id <run_id>` exits 0.`
The acceptance criterion is a command exit code, not a vibe — that's what the goal-checker
(and you) grade against. After that: build the `maas` adapter (#2) to validate generalization.

## Tried & outcome
- 2026-06-23 bootstrap — chose to under-build on purpose (no cron / worktree / connector /
  sub-agent fan-out for a one-off bootstrap). Over-scaffolding a bootstrap is the exact
  "cognitive surrender / over-looping" failure the doctrine warns against. Each non-action
  is recorded above so it can be audited, not guessed.
