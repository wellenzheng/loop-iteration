# Plugin-ization & Generic Adapter — Design

- **Date:** 2026-06-23
- **Status:** Approved (brainstormed), pending implementation plan
- **Project:** `loop-iteration`
- **Builds on:** [Self-iteration loop design](2026-06-23-self-iteration-loop-design.md) (already implemented, 30 tests green on `main`)
- **Governing doctrine:** [loop-engineering](../../../skills/loop-engineering/SKILL.md) (to live at plugin root after this refactor)

## 1. Goal & motivation

The self-iteration loop works, but its current shape couples the **generic mechanism** to a
**specific toy agent**: the adapter lives at `adapters/toy/` (with `run_case.py`, `apply_variant.py`,
`agent_files/`), which makes it look like every integrating user must write an adapter.

The goal: make this a **downloadable Claude Code plugin** where an integrating user writes **only an
eval spec** (their cases + gates + judge + goal). For Claude-Code-native agents — the common case —
**no adapter code is required**: a generic adapter (shipped with the plugin) covers it. Only exotic
agents that aren't `claude -p`-invokable (e.g. maas-as-a-service) need a small escape-hatch function.

This design refactors `loop-iteration` into a plugin source and replaces the toy-specific adapter
with a generic Claude-native one + an escape hatch.

## 2. Current state (what exists on `main`)

- `src/loop_iter/` — 8 modules: `scoring`, `gates`, `judge`, `adapter`, `case_runner`, `goal_check`,
  `state`, `llm_client`.
- `adapters/toy/` — `run_case.py`, `apply_variant.py`, `agent_files/` (the conflation of "generic
  mechanism" + "sample agent").
- `evals/toy-basic/` — `goal.yaml`, `cases.json`, `gates.py`, `judge.md`.
- `.claude/skills/{loop-engineering, self-iterate, case-evaluator}`, `.claude/agents/{harness-rewriter, goal-checker}`.
- 30 tests green; merged to `main`.

## 3. Key decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| P1 | **Repo = plugin source; Python bundled as `scripts/`** | Single source of truth. Matches how `skill-creator`/`superpowers` ship (`.claude-plugin/plugin.json` + `skills/` + `agents/` + `scripts/` + `assets/`; skills call bundled Python by relative path). No PyPI publish, no extra user install beyond the plugin. |
| P2 | **Harness scope = convention + override** | Default iterates the standard Claude Code "brain" (`CLAUDE.md`, `AGENTS.md`, `.claude/skills/**`, `.claude/agents/**`) so a standard agent needs **zero config**. Override via the `harness:` key in `goal.yaml` when an agent's harness lives elsewhere (one config file, no second file). |
| P3 | **Generic `run_case` = `claude -p` in worktree; drop-in `run_case.py` escape hatch** | `claude -p` covers every Claude-Code-native agent (its CLAUDE.md/skills auto-load when cwd = worktree). Non-Claude agents drop one `run_case.py` — a single function, not a whole adapter dir. This is what the `maas` adapter #2 will validate. |

## 4. Design

### 4.1 Plugin layout & packaging (decision P1)

The repo becomes the plugin source, following the `skill-creator`/`superpowers` convention
(root-level `.claude-plugin/plugin.json` + `skills/` + `agents/` + `scripts/`). Skills move out of
`.claude/` to the plugin root (where plugins are discovered); the Python core moves from `src/loop_iter/`
to `scripts/loop_iter/` so it ships with the plugin and is callable by relative path.

```
loop-iteration/                          ← repo = plugin source
├── .claude-plugin/plugin.json           ← {name:"self-iterate", description, author}
├── skills/
│   ├── loop-engineering/SKILL.md          (doctrine — moved from .claude/skills/)
│   ├── self-iterate/SKILL.md              (one round — updated for generic adapter)
│   └── case-evaluator/SKILL.md            (checker — updated)
├── agents/
│   ├── harness-rewriter.md                (maker — updated to edit harness_paths)
│   └── goal-checker.md                    (reviewer)
├── commands/
│   └── self-iterate.md                    ← "/self-iterate toward <goal>" slash command
├── scripts/
│   └── loop_iter/                         ← Python core (moved from src/) + generic adapter
│       ├── scoring.py gates.py judge.py adapter.py state.py llm_client.py   (unchanged logic)
│       ├── case_runner.py goal_check.py    (updated: use generic adapter)
│       ├── adapter_generic.py              (NEW: resolve_harness, run_case default + escape hatch)
│       └── cli.py                          (NEW: unified CLI: apply-variant, case-run, goal-check, setup)
├── examples/
│   └── toy/.self-iterate/toy-basic/      ← dogfood, now an example of the user-facing layout
├── tests/                                 ← kept; import from scripts/loop_iter (pythonpath)
├── docs/  README.md  .loop/  pyproject.toml
```

**What ships (on install):** `skills/` + `agents/` + `commands/` + `scripts/loop_iter/` + `examples/`.
**What the user writes (in their own agent repo):** only a `.self-iterate/<goal>/` eval spec.

**Python dependencies:** the plugin assumes Python 3.11+ is available. A `/self-iterate setup`
command (a bundled script the skill calls) bootstraps a venv and installs `pyyaml`/`httpx`; later
runs reuse it. This mirrors the "plugin bundles scripts, assumes Python" model — no PyPI publish.

**Dev / dogfooding:** the plugin-source repo still runs its own `pytest` (importing from
`scripts/loop_iter/`). To try the plugin live you install it like a real plugin (symlink into
`~/.claude/plugins/`) so the root `skills/` are discovered — documented as the dev workflow, not
auto-wired.

### 4.2 Generic adapter contract (decisions P2 + P3)

Three functions, each with a shipped default and (where it matters) a user override:

| Function | Generic default (shipped) | User override |
|---|---|---|
| `resolve_harness` | `[CLAUDE.md, AGENTS.md, .claude/skills/**, .claude/agents/**]` | `harness:` key in `goal.yaml` (paths/globs) |
| `apply_variant` | `git worktree add --detach` of the user's repo → maker edits there; source untouched (unchanged `adapter.py`) | — |
| `run_case` | `claude -p "<query>"` in the worktree | drop a `run_case.py` in `.self-iterate/<goal>/` (or project-root `.self-iterate/`) |

**`run_case` escape hatch (the maas case):** the generic runner checks for a user `run_case.py` in
the eval dir before falling back to `claude -p`. If present, it loads the file and calls the user's
`run_case(case, worktree, harness_paths) -> Result`. This is the **only** code a non-Claude-CLI agent
owner writes — one small function, no `apply_variant`, no adapter directory. The `maas` adapter #2
validates exactly this.

**Config (one file, optional):** `.self-iterate/<goal>/goal.yaml` already holds threshold, weights,
regression policy. We add the agent-invocation knobs there — same file, no second config surface:

```yaml
# .self-iterate/<goal>/goal.yaml  (user-side)
threshold: 0.85
max_rounds: 3
regression: block
weights: { gates: 2.0, conciseness: 1.0 }
agent:                          # optional, overrides the Claude-native default
  model: claude-sonnet-4-6
  permission_mode: bypassPermissions
  timeout: 120
  extra_args: []
harness:                        # optional, overrides the default scope convention
  - CLAUDE.md
  - prompts/**
```

**Why this works:** `resolve_harness` and `apply_variant` are already identical across all Claude
Code agents (standard files + git) — no per-user code there. `run_case` is the only truly
agent-specific piece, and for Claude-native it's covered by `claude -p`; the escape hatch covers the
minority. The one thing every user must write (the eval spec: cases + gates + judge) is exactly the
customization they want.

### 4.3 User-facing contract & runtime flow

**1. Install (once):**
```bash
# place the plugin in your Claude Code plugins dir (or your usual plugin install path)
# then, in any repo:
/self-iterate setup     # bootstraps a venv + installs pyyaml/httpx (reuses an existing venv)
```

**2. Write an eval spec in their agent repo** — the only thing they author:
```
their-agent-repo/
└── .self-iterate/
    └── <goal>/                 # e.g. "support-tone", "accuracy"
        ├── goal.yaml           # threshold, weights, regression, optional agent/harness overrides
        ├── cases.json          # their QA set
        ├── gates.py            # their programmatic gates (GATES = {name: fn})
        └── judge.md            # their LLM-rubric dims
        # optional: goal.yaml 'agent:'/'harness:' overrides; run_case.py (non-Claude escape hatch)
```

**3. Run:**
```
/self-iterate toward <goal>
# or just tell Claude: "self-iterate toward <goal>"
```

**Runtime flow** — the skill (from the installed plugin) runs in the user's cwd and calls the bundled
Python by its bundled path, bridging *user repo* (eval spec + harness) ↔ *plugin core* (scoring /
goal-check):

```
/self-iterate toward <goal>  (runs in the user's repo)
  │
  self-iterate skill (plugin):
  1. read .self-iterate/<goal>/ from cwd                        ← user repo
  2. stage:  python <plugin>/scripts/loop_iter/cli.py apply-variant
     → git worktree of cwd; resolve_harness (convention + goal.yaml `harness:`)
  3. dispatch harness-rewriter (maker) on the worktree; edits harness_paths
  4. dispatch case-evaluator: per case → user gates + judge + (escape-hatch run_case.py OR claude -p)
     → python <plugin>/scripts/loop_iter/cli.py case-run … writes scores
  5. python <plugin>/scripts/loop_iter/cli.py goal-check … → verdict + exit code
  6. write state into the USER repo: their-agent-repo/.loop/iterate/<run_id>/
  → wrapped by run-until-done (ralph/autopilot), goal-checker as the reviewer
```

**Where state lands:** always in the **user's repo** at `.loop/iterate/<run_id>/` (`progress.md`,
`scores.json`, `variants/round_N/`) — never inside the plugin. The plugin is stateless; each repo
keeps its own run history. The loop never auto-merges — the human merges the winning worktree into
their agent repo after reviewing `report.md`.

**Slash command (`commands/self-iterate.md`):** a thin dispatcher that (a) parses `toward <goal>`,
(b) ensures the Python env is ready (runs `setup` if missing), (c) hands off to the `self-iterate`
skill. It exists for discoverability and one-shot env bootstrap; the real logic stays in the skill.

### 4.4 Refactor mapping, testing & migration

**Current → target** (each commit green):

| Current | → Target | Notes |
|---|---|---|
| `.claude/skills/{loop-engineering,self-iterate,case-evaluator}` | `skills/…` | move to plugin root (discovery convention) |
| `.claude/agents/{harness-rewriter,goal-checker}` | `agents/…` | same; `harness-rewriter` updated to edit `harness_paths` |
| `src/loop_iter/*.py` (8 modules) | `scripts/loop_iter/*.py` | bundled with plugin |
| `case_runner._cli` + `goal_check._cli` (`__main__` blocks) | `scripts/loop_iter/cli.py` | **one** unified entry with subcommands (`apply-variant`, `case-run`, `goal-check`, `setup`) — simpler to call |
| `adapters/toy/` + `evals/toy-basic/` | `examples/toy/.self-iterate/toy-basic/` | toy → an example showing the user-facing layout |
| — | `.claude-plugin/plugin.json`, `commands/self-iterate.md`, `scripts/loop_iter/adapter_generic.py` | new |

**New module — `adapter_generic.py`** (the "no-adapter" core):
- `resolve_harness(eval_dir, repo_root) -> list[Path]` — default globs (`CLAUDE.md`, `AGENTS.md`,
  `.claude/skills/**`, `.claude/agents/**`), `goal.yaml` `harness:` override if present.
- `load_run_case(eval_dir) -> callable | None` — returns the user's `run_case` if `run_case.py` is
  present, else `None` (caller uses the `claude -p` default).
- `run_case_default(case, worktree, config) -> Result` — `claude -p` invocation (generalized from the toy).
- `apply_variant` / `snapshot_variant` / `remove_worktree` — unchanged in current `adapter.py`.

**Testing:** the existing 30 tests are preserved (`pyproject` `pythonpath` → `scripts`; imports stay
`loop_iter.…`). New tests: `resolve_harness` (default globs + override), `load_run_case` (loads when
present, None when absent), `cli` dispatch. The toy example's eval spec remains an end-to-end fixture.

**Migration safety:** currently on `main` → branch to `feat/plugin-ization`. Plan order: moves first
(imports repaired via `pythonpath`), then new pieces, then skill/agent updates to call the unified
CLI — every commit green, no big-bang.

## 5. Scope (YAGNI)

**In:** plugin layout + manifest; generic adapter (`resolve_harness` + `claude -p` default +
`run_case.py` escape hatch + unified `cli`); toy → `examples/` with `.self-iterate/`;
`/self-iterate setup` + slash command; new tests.

**Out (explicitly, for later):** publishing to a plugin marketplace; auto-update; multi-goal
concurrency; the **maas adapter** (the escape-hatch validation — separate work); any GUI.

## 6. Open questions / future

- **maas adapter #2** — the first real exercise of the `run_case.py` escape hatch (call the MaaS
  service instead of `claude -p`). Validates the generalization claim end-to-end on a non-Claude agent.
- **Plugin distribution** — once the plugin-source layout is solid, decide install path (marketplace
  vs manual symlink vs git clone).
- **Parallel per-case eval** — when case counts grow, the checker fans out (parallel sub-agents or a
  workflow stage); deferred.
