---
name: self-iterate-setup
description: Interactive setup for the self-iterate loop. Reads the current repo, detects the agent's entry type, asks the user for the optimization goal, proposes a complete eval spec (goal.yaml/cases.json/gates.py/judge.md/quality.md), confirms each piece, writes it to .self-iterate/<goal>/, self-validates via cli `validate-spec`, then resolves the Python env via cli `setup`. Use when the user runs "/self-iterate setup".
---

# self-iterate-setup (interactive)

You bootstrap a self-iterate eval spec for the agent in the user's current repo (cwd), then resolve
its Python env. You PROPOSE drafts and CONFIRM each with the user before writing — never silently
invent an optimization target. Run cli under the plugin's interpreter when needed:
`<plugin>/scripts/loop_iter/cli.py` (use `python` for validate-spec; `setup` resolves its own venv).

## Workflow

1. **Read the repo.** Skim for the agent's harness + entry:
   - harness candidates: `CLAUDE.md`, `AGENTS.md`, `.claude/skills/**/*.md`, `.claude/agents/**/*.md`.
   - entry signals: `pyproject.toml`/`setup.py` (python module + cli), `package.json` (node cli), a
     `run`/`main` script, an existing `CLAUDE.md` (claude-p agent). Note the agent's framework if any.
   - existing `.self-iterate/<goal>/`? If yes, ask whether to reuse or overwrite.

2. **Detect agent type + propose `agent:` config.** Pick one and CONFIRM with the user:
   - `claude-p` (default) if the repo is a Claude-Code-native agent (has CLAUDE.md/skills).
   - `command` if there's a CLI: propose `cmd` with `{variant_dir}`/`{query}` placeholders.
   - `python-import` if there's an in-process entry: propose `module`/`entry` + `agent.venv` (e.g.
     `.venv`) — note the user must provide a ~5-line `entry(query, variant_dir, **extra)` shim (or a
     `run_case.py`).
   - `custom`/`run_case.py` escape hatch for bespoke agents.
   If `agent.venv` is needed, ask which venv dir has the agent's deps.

3. **Ask the goal.** Ask the user, in one question, what the optimization target is (e.g. "make
   escalations decisive", "answer in one word"). This becomes the `<goal>` dir name and the spec's
   intent. Propose a kebab-case dir name and CONFIRM.

4. **Propose the eval spec drafts** (one block, then confirm piece-by-piece):
   - `goal.yaml`: `threshold` (propose 0.85), `max_rounds` (propose 3), `regression: block`,
     `weights` (gates heavy + 1 judge dim), the `agent:` block from step 2, `harness:` list (the
     editable files from step 1). `quality_tolerance: 0.5`.
   - `cases.json`: 3-6 cases (id/query/expected-or-not) that probe the goal. Ask the user for real
     representative inputs/outputs if they have them; otherwise propose from the goal.
   - `gates.py`: programmatic, verifiable gates matching the goal (e.g. decisive_escalation,
     is_substantive). `GATES = {name: fn}` where `fn(result, case) -> {"passed": bool}`. Gates must
     read `result["output"]`.
   - `judge.md`: 1-2 LLM-rubric dims (e.g. conciseness, escalation_quality) 0-10.
   - `quality.md`: clarity / no_overfit (note: auto-detected) / maintainability rubric. (Optional but
     recommended — recommend including it.)
   CONFIRM each file's content with the user before writing. Adjust on feedback.

5. **Write the spec** to `.self-iterate/<goal>/` (goal.yaml, cases.json, gates.py, judge.md,
   quality.md, and the entry shim / run_case.py if the agent type needs one).

6. **Self-validate.** Run:
   ```
   python <plugin>/scripts/loop_iter/cli.py validate-spec --eval .self-iterate/<goal>
   ```
   If `valid` is false, read the `problems`, FIX the offending file, re-run until valid. Surface
   `warnings` to the user (e.g. quality.md absent, agent.type unset) and confirm whether to address.

7. **Resolve the Python env.** Run:
   ```
   python <plugin>/scripts/loop_iter/cli.py setup --eval .self-iterate/<goal>
   ```
   This picks `agent.venv` if set (has the agent's deps) else bootstraps `.self-iterate/.venv`, and
   records the interpreter at `.self-iterate/.python`. (For python-import agents, confirm the shim
   imports the agent under that venv — ask the user to run one case manually if unsure.)

8. **Report.** Tell the user the spec is ready at `.self-iterate/<goal>/` and the next step is
   `/self-iterate start <goal>`.

## Rules
- PROPOSE then CONFIRM. Never write the spec without the user confirming the goal + each file.
- Gates must be programmatic and verifiable (a command exit code / boolean), not LLM vibes — the
  loop's stop condition leans on them.
- Don't hardcode eval answers into the proposed harness/gates.
- If the repo has no clear agent entry, ask the user how the agent is invoked rather than guessing.
