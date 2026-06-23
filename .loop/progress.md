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

## In flight
(none)

## Blocked
- **No connectors wired (block 4)** — by design. Wire on the first loop that needs to
  *act* in the environment (open a PR, update a ticket, ping a channel). Wiring one now
  would be intent debt — we don't yet know which env this project ships into.
- **No product decided** — `src/` / app skeleton deliberately not created. Picking the
  product is the first *real* loop, not a bootstrap decision.

## Next
The human decides the first real loop goal. Write it here as one line:
`- [ ] <thing> — done when: <verifiable command>`.
The acceptance criterion must be a command exit code, not a vibe — that's what a checker
(human or sub-agent) grades against.

## Tried & outcome
- 2026-06-23 bootstrap — chose to under-build on purpose (no cron / worktree / connector /
  sub-agent fan-out for a one-off bootstrap). Over-scaffolding a bootstrap is the exact
  "cognitive surrender / over-looping" failure the doctrine warns against. Each non-action
  is recorded above so it can be audited, not guessed.
