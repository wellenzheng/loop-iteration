---
name: self-iterate-setup
description: Interactive setup for the self-iterate loop. Reads the current repo, detects the agent's entry type, asks the user for the optimization goal, proposes a complete eval spec (goal.yaml/cases.json/gates.py/judge.md/quality.md), confirms each piece, writes it to .self-iterate/<goal>/, self-validates via cli `validate-spec`, then resolves the Python env via cli `setup`. Use when the user runs "/self-iterate setup".
---

# self-iterate-setup (interactive)

You bootstrap a self-iterate eval spec for the agent in the user's current repo (cwd), then resolve
its Python env. You PROPOSE drafts and CONFIRM each with the user before writing — never silently
invent an optimization target. Run cli under the plugin's interpreter when needed:
`<plugin>/scripts/loop_iter/cli.py`. Run `setup` first (resolves `.self-iterate/.python`), then run
`validate-spec` under that interpreter.

## Loop mechanics (so you don't re-derive from source)

- The loop creates a FULL git worktree of the repo at baseline each round. The maker edits the
  worktree's harness files; the source repo is never mutated mid-loop.
- `variant_dir` / the service launch dir = the worktree (or `worktree/<variant_subdir>` for
  python-import). This is how a variant harness reaches the running agent.
- `harness:` in goal.yaml = the files the maker may edit + what snapshot/diff capture. BUT whether
  an edited file actually REACHES the running agent depends on the adapter:
  - `claude-p`: agent runs `claude -p` in the worktree cwd → reads CLAUDE.md/skills from there. All
    harness edits reach.
  - `local-service`: the service is started FROM the worktree each round → it reads harness from its
    launch dir. Harness edits reach IF the service reads harness from cwd (confirm with the user).
  - `python-import`: only `skills_dir=variant_dir` reaches the agent; anything the shim imports via
    `module_path` (e.g. a system prompt) loads from the repo, NOT the worktree → those harness edits
    are inert. So for python-import, `harness:` should be only the skills the shim wires to
    `variant_dir`.
- So propose `harness:` = only files that actually reach the agent for the detected adapter type.

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
   - `local-service` if the agent runs as a local HTTP service on `localhost:port`: ask the user for
     the start command (it launches from the worktree — confirm the service reads its harness from
     its cwd/launch dir, else local-service won't apply variants and you must fall back to
     `python-import`), the port (or 0 for auto), a ready endpoint (health), the case endpoint, the
     request body template (`{query}`), and the response JSON path to the answer. Write these into
     `agent:` (type/start/port/ready/endpoint/request/response_path).
   - `custom`/`run_case.py` escape hatch for bespoke agents.
   If `agent.venv` is needed, ask which venv dir has the agent's deps.

3. **Ask the goal.** First confirm WHICH agent in the repo is the optimization target — the repo may
   contain several (e.g. a 客服 agent vs a zdata agent). Ask the user explicitly; do NOT default to
   one. Then ask, in one question, what the optimization target is for that agent (e.g. "make
   escalations decisive", "answer in one word"). This becomes the `<goal>` dir name and the spec's
   intent. Propose a kebab-case dir name and CONFIRM.

4. **Propose the eval spec drafts** (one block, then confirm piece-by-piece):
   - `goal.yaml`: `threshold` (propose 0.85), `max_rounds` (propose 3), `regression: block`,
     `weights` (gates heavy + 1 judge dim), the `agent:` block from step 2, `harness:` list = ONLY
     files that actually reach the agent for the detected adapter (see Loop mechanics). For a
     zai_adk / skills-based agent (python-import or local-service that loads skills_dir), that's
     `skills/**/*.md` — NOT CLAUDE.md/AGENTS.md unless the agent reads them. `quality_tolerance: 0.5`.
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

6. **Resolve the Python env.** Run:
   ```
   python <plugin>/scripts/loop_iter/cli.py setup --eval .self-iterate/<goal>
   ```
   This picks `agent.venv` if set (has the agent's deps) else bootstraps `.self-iterate/.venv`, and
   records the interpreter at `.self-iterate/.python` (that venv has pyyaml+httpx, so validate-spec
   can run). For python-import agents, confirm the shim imports the agent under that venv — ask the
   user to run one case manually if unsure.

7. **Self-validate.** Run validate-spec under the recorded interpreter:
   ```
   "$(cat .self-iterate/.python)" <plugin>/scripts/loop_iter/cli.py validate-spec --eval .self-iterate/<goal>
   ```
   If `valid` is false, read the `problems`, FIX the offending file, re-run until valid. Surface
   `warnings` to the user (e.g. quality.md absent, agent.type unset) and confirm whether to address.
   (If validate-spec reports a pyyaml problem, the env didn't resolve — re-run `setup`.)
   After validate-spec passes, run a smoke test:
   ```
   python <plugin>/scripts/loop_iter/cli.py smoke --eval .self-iterate/<goal>
   ```
   It runs ONE case through the resolved adapter (for local-service: starts the service from the
   repo, POSTs case[0], stops).
   (smoke starts from the repo to verify the baseline entry; the loop's case-run starts the service
   from the worktree each round to apply the variant harness.)
   If it errors, fix the entry/config and re-run until non-error. Only
   then is setup done — this catches a broken entry before `/self-iterate start` burns real calls.

8. **Report.** Tell the user the spec is ready at `.self-iterate/<goal>/` and the next step is
   `/self-iterate start <goal>`.

## Rules
- PROPOSE then CONFIRM. Never write the spec without the user confirming the goal + each file.
- Gates must be programmatic and verifiable (a command exit code / boolean), not LLM vibes — the
  loop's stop condition leans on them.
- Don't hardcode eval answers into the proposed harness/gates.
- If the repo has no clear agent entry, ask the user how the agent is invoked rather than guessing.
