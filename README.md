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

## self-iterate (the plugin)

This repo **is** a Claude Code plugin that self-iterates any agent's harness
(prompt/skills/tools) until a verifiable goal is met. Design:
[spec](docs/superpowers/specs/2026-06-23-plugin-ization-design.md).

### Install
Place this repo in your Claude Code plugins dir (or your usual plugin-install path).
Requires Python 3.11+. Then in any repo:
```
/self-iterate setup        # interactive: reads the repo, proposes the eval spec (goal.yaml/cases.json/
                           # gates.py/rubric.md/quality.md), confirms each with you, writes .self-iterate/<goal>/,
                           # self-validates, then resolves the Python env (agent.venv or bootstrap -> .self-iterate/.python).
```

### Use it on your agent
In your agent's repo, run `/self-iterate setup` — it proposes the eval spec for you to confirm. Or
hand-write it:
```
.self-iterate/<goal>/
  goal.yaml     # threshold, weights, regression, optional agent:/harness: overrides
  cases.json    # your QA set
  gates.py      # your programmatic gates (GATES = {name: fn})
  rubric.md     # your LLM-rubric dims
  quality.md    # OPTIONAL — rubric judging the harness FILES themselves (guardrail: a round whose
                #            quality regresses below baseline can't satisfy the goal or be the winner)
  # optional run_case.py — escape hatch for non-Claude-CLI agents (e.g. a service)
```

#### Adapter type (`agent.type` in goal.yaml)

How each case is run against your agent — declarative, no code for the common cases:

| type | when | what you provide |
|---|---|---|
| `claude-p` (default) | Claude-Code-native agent | nothing (runs `claude -p` in the worktree) |
| `command` | agent has a CLI | `cmd` with `{variant_dir}`/`{query}` substituted, e.g. `["python","-m","src.agent.cli","--skills-dir","{variant_dir}","{query}"]` |
| `python-import` | in-process agent (e.g. maas) | `module` + `entry` + `agent.venv: .venv`; a ~5-line `entry(query, variant_dir, **extra)` shim that loads your agent with `skills_dir=variant_dir` |
| `custom` / omitted + `run_case.py` | bespoke | a drop-in `run_case.py` |

Example (`command`, zero code if your agent has a CLI):

```yaml
agent:
  type: command
  cmd: ["python", "-m", "my_agent", "--skills-dir", "{variant_dir}", "{query}"]
  variant_subdir: skills
```
Then:
```
/self-iterate toward <goal>
```
A generic adapter handles Claude-native agents (no adapter code): it iterates the standard
harness (`CLAUDE.md`, `AGENTS.md`, `.claude/skills/**`, `.claude/agents/**`) in an isolated
git worktree, runs each case via `claude -p`, and scores with your gates + judge. State lands
in your repo at `.self-iterate/runs/<run_id>/`. The loop never auto-merges — you merge the winner.

### Point it at a non-Claude agent
Drop a `run_case.py` defining `run_case(case, worktree, harness_paths) -> result` into
`.self-iterate/<goal>/`. The generic runner uses it instead of `claude -p`. That's the only
code a non-Claude agent needs.

### Example
See [`examples/toy/`](examples/toy/) — a one-word-answerer agent + its `.self-iterate/toy-basic/`
eval spec, ready to `/self-iterate toward toy-basic`.
