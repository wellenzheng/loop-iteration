# loop-iteration

A project developed **loop-first**: work is designed as autonomous loops, not as one-shot
prompts. The doctrine lives in [`.claude/skills/loop-engineering/SKILL.md`](.claude/skills/loop-engineering/SKILL.md) — read it for the
why. This file is the project-level playbook: how the five building blocks + state map onto
*this* codebase, and how you drive development.

> Build the loop. Stay the engineer.

## The five building blocks + state — handles in this project

| Block | What it is | Concrete handle here |
|---|---|---|
| **Automations** (heartbeat) | recurring discovery/triage on a schedule | `/loop` (cadence), `ralph`/`autopilot` (run-until-done, separate reviewer), cron, hooks (`settings.json`), GitHub Actions (the only one that survives a closed laptop) |
| **Worktrees** | isolate parallel agents so they don't collide | `git worktree`, the `EnterWorktree` tool, `isolation: worktree` on a subagent |
| **Skills** | codify project knowledge so it stops being re-derived | `.claude/skills/` — the `loop-engineering` doctrine skill lives here; add a skill whenever a convention or gotcha crystallizes |
| **Connectors / MCP** | let the loop *act* in the environment, not just report | MCP servers for GitHub / issue tracker / Slack — **not wired yet**; wire on the first loop that needs to act |
| **Sub-agents** | keep the maker away from the checker | one explores, one implements, one verifies against the spec; the maker never grades its own work |
| **+ State** (the spine) | on-disk memory that survives between runs | [`.loop/progress.md`](.loop/progress.md) — read first, write before stopping |

## How to drive development (the loop shape used here)

1. **Read [`.loop/progress.md`](.loop/progress.md)** — know where the last run stopped.
2. **Run the pre-flight checklist** (8 questions, in the doctrine skill). Most tasks need
   only a few; the point is to decide deliberately. The two that matter most:
   - *One-shot or loop?* — don't bolt a loop onto a five-minute task.
   - *Goal & verifiable stopping condition?* — "done" must be a command exit code.
3. **Pick the shape:**
   - `/loop` — recurring work on a cadence.
   - `ralph`/`autopilot` — run-until-done for one bounded goal (the reviewer is a separate
     agent by design = the maker/checker split).
   - worktree-isolated subagents — parallel features.
4. **Maker drafts → a *different* checker verifies** against the spec + tests.
5. **Read the diff yourself.** Update `.loop/progress.md`. Capture any new convention as a
   skill under `.claude/skills/`.

## The three things the loop will not do for you

- **Verification is still on you** — "done" is a claim, not a proof. Ship code you
  confirmed works.
- **Your understanding rots** — the faster the loop ships code you didn't write, the bigger
  the gap. Read what the loop made.
- **Cognitive surrender is the dangerous posture** — loop to move faster on work you
  understand, not to avoid understanding it. Keep an opinion.

## Status

Bootstrap complete. The project is a loop-first empty vessel on purpose: there is no app
skeleton yet, because picking the product is the **first real loop**, not a bootstrap
decision. See [`.loop/progress.md`](.loop/progress.md) → *Next*.

## Self-iteration loop (the product)

This repo *is* an agent-harness self-iteration loop. It iterates an agent's harness
(prompt/skills/tools) until a verifiable goal is met. See
[the design](docs/superpowers/specs/2026-06-23-self-iteration-loop-design.md).

### Run it on the toy agent (dogfood)

```bash
. .venv/bin/activate
export OPENAI_API_KEY=...      # for the LLM judge
export OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
export OPENAI_MODEL=glm-4.7

# One round, interactively (read state, stage worktree, maker, checker, goal-check):
#   tell Claude Code: "self-iterate toy toward toy-basic, run_id $(date +%Y%m%d_%H%M%S)_toy"

# Unattended (run-until-done until the goal is met):
#   use ralph/autopilot with self-iterate as the worker and goal-checker as the reviewer
```

State lands in `.loop/iterate/<run_id>/` (`progress.md`, `scores.json`, `variants/round_N/`).
The loop never auto-merges — review `report.md` and merge the winning variant yourself.

### Point it at your own agent

1. **Adapter** — `adapters/<my-agent>/{run_case.py, apply_variant.py, agent_files/}`
   (copy `adapters/toy/` and change `run_case` to invoke your agent).
2. **Goal** — `evals/<my-goal>/{goal.yaml, cases.json, gates.py, judge.md}`
   (copy `evals/toy-basic/` and edit the gates/rubric/threshold).
3. **Run** — in Claude Code: "self-iterate `<my-agent>` toward `<my-goal>`".
