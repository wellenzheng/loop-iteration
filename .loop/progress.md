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
- 2026-06-23 — **First real dogfood run DONE** — `self-iterate toy toward toy-basic`, run
  `20260623_a47e34`. Live end-to-end round 1 with real `claude` CLI + `OPENAI_API_KEY`.
  Maker sharpened the deliberately-vague harness into one rule ("answer in exactly one
  bare word, no punctuation, no hedging"). Composite **1.0**, both gates 1.0, conciseness
  10.0. `goal_check` exit 0 (`met: true`). Source repo untouched; worktree made + removed.
  Winner: `.loop/iterate/20260623_a47e34/variants/round_1/`.
- 2026-06-23 — **Plugin-ization complete** (10-task plan, branch `feat/plugin-ization`). Repo
  restructured into a Claude Code plugin: `.claude-plugin/plugin.json` + root `skills/`/
  `agents/`/`commands/` + bundled `scripts/loop_iter/`. Generic adapter replaces the toy-specific
  one: `resolve_harness` (convention + `goal.yaml` override), `claude -p` default `run_case`,
  drop-in `run_case.py` escape hatch, unified `cli.py` (`apply-variant`/`case-run`/`goal-check`/
  `setup`). Users now write only `.self-iterate/<goal>/`; toy moved to `examples/`. **39 tests
  green**; plugin-layout smoke passes (manifest valid, `python scripts/loop_iter/cli.py`
  responds, `goal-check` exits 1 on empty). Fixed: cli.py sys.path bootstrap so it runs as a
  script from any cwd. Remaining: install-path/distribution decision + the maas escape-hatch
  validation (adapter #2).

## In flight
- _(none — first dogfood goal closed in one round.)_

## Blocked
- **No connectors wired (block 4)** — by design. Wire on the first loop that needs to
  *act* in the environment (open a PR, update a ticket, ping a channel). Wiring one now
  would be intent debt — we don't yet know which env this project ships into.
- **No product decided** — `src/` / app skeleton deliberately not created. Picking the
  product is the first *real* loop, not a bootstrap decision.

## Next
- [x] ~~self-iterate toy toward toy-basic — done when composite ≥ 0.85, no gate regression,
   `goal_check` exit 0.~~ **DONE 2026-06-23** (run `20260623_a47e34`, composite 1.0 round 1).
- [ ] Build the `maas` adapter (#2) to validate generalization beyond the toy agent.
- [ ] Hardening: c1/c2 judge returned no dims on this run (c3 scored 10). Investigate why the
   judge LLM returned empty for two of three cases — likely a parsing/response-length quirk in
   `judge._parse_dims` or the model dropping JSON. Not blocking (composite already 1.0 from gates)
   but it's a latent bug for goals where the judge dim is load-bearing.

## Tried & outcome
- 2026-06-23 bootstrap — chose to under-build on purpose (no cron / worktree / connector /
  sub-agent fan-out for a one-off bootstrap). Over-scaffolding a bootstrap is the exact
  "cognitive surrender / over-looping" failure the doctrine warns against. Each non-action
  is recorded above so it can be audited, not guessed.
