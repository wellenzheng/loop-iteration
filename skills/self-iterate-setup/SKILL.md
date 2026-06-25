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

**Investigate-first.** Read the repo's code to INFER and PROPOSE every config value (entry type,
start command, port, request/response shape, harness files, even candidate gates). The user
CONFIRMS or tweaks your proposals — do NOT ask the user to hand-provide what you can read from the
code. Reserve open-ended questions for things genuinely not inferable: the optimization GOAL (user
intent) and WHICH agent when several exist.

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

2. **Detect agent type + propose `agent:` config.** INVESTIGATE the repo to infer the entry, then
   propose + CONFIRM. Pick one:
   - `claude-p` (default) if the repo is a Claude-Code-native agent (has CLAUDE.md/skills).
   - `command` if there's a CLI: read `pyproject.toml`/scripts to propose `cmd` with
     `{variant_dir}`/`{query}` placeholders.
   - `python-import` if there's an in-process entry: read the agent's construction code (how it's
     built — `create_agent`, skills_dir, system prompt) and WRITE the `entry(query, variant_dir,
     **extra)` shim yourself (and `run_case.py` if needed) so it rebuilds the agent with
     `skills_dir=variant_dir`. Propose `module`/`entry` + `agent.venv` (detect the venv dir —
     `.venv`/`venv`/uv — by checking for `bin/python`).
   - `local-service` if the agent runs as a local HTTP service on `localhost:port`. INVESTIGATE the
     code to propose the WHOLE config — do not ask the user to hand-provide it:
     - `start`: read `pyproject.toml` `[project.scripts]` / a main module / docker-compose / README
       → propose the launch command (it runs from the worktree, so the service loads the variant
       harness).
     - `port` + `ready`: read the service's default port + any `/health` route → propose (or `0` for
       auto).
     - `endpoint` + `request` + `response_path`: read the case route handler (e.g. the `/v1/chat`
       handler) → propose the `request` body template with `{query}` and the `response_path` (dotted
       JSON path) to the answer text.
     - **harness-from-cwd check (critical):** read the agent-construction code — does it load
       skills/prompts from a path RELATIVE to its launch dir (cwd) or an ABSOLUTE/fixed path? If
       relative/cwd → local-service applies variants ✓. If absolute/fixed → variant harness won't
       reach the service; propose either (a) a one-line fix to the service to read from cwd, or
       (b) fall back to `python-import` (in-process shim).
     Write the proposed `agent:` (type/start/port/ready/endpoint/request/response_path) and CONFIRM.
   - **bespoke protocol (SSE / JWT / custom event format)** — if the agent's endpoint streams (SSE)
     or needs auth/custom parsing that the declarative `local-service` config can't express (e.g.
     maas `/v1/chat` is SSE-only with a custom event encoder + JWT): INVESTIGATE the agent's code
     (the route handler, the SSE encoder, the auth module) and WRITE a `.self-iterate/<goal>/adapter.py`
     defining `start(worktree)` (launch the real service FROM the worktree so it loads the variant
     harness), `run_case(case, worktree)` (call the endpoint with the right auth + parse the bespoke
     response into `{output, error}`), and `stop()` (kill the service). Set `agent.type: custom`.
     The bespoke protocol lives in this per-agent script — not in the plugin. Then smoke-test it.
   - `custom`/`run_case.py` escape hatch for bespoke agents.
   If `agent.venv` is needed, detect it (don't ask) by checking for `bin/python` under `.venv`/
   `venv`/`.python-version`/uv.

3. **Ask the goal.** First INVESTIGATE which agents the repo contains (multiple entry points /
   services?) and LIST them to the user; confirm WHICH is the optimization target — do NOT default
   to one. Then ask, in one question, what the optimization target is for that agent (the goal is
   user intent — not inferable; e.g. "make escalations decisive", "answer in one word"). This
   becomes the `<goal>` dir name and the spec's intent. Propose a kebab-case dir name and CONFIRM.

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
   quality.md, and the entry shim / run_case.py / adapter.py if the agent type needs one).

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
- INVESTIGATE-FIRST: read the code to infer + propose every config (entry, start/port/endpoint/
  request/response, harness, venv, candidate gates). The user CONFIRMS or tweaks — don't ask them
  to hand-provide what's in the code. Reserve open questions for the GOAL (user intent) and which
  agent when several exist.
- PROPOSE then CONFIRM. Never write the spec without the user confirming the goal + each file.
- Gates must be programmatic and verifiable (a command exit code / boolean), not LLM vibes — the
  loop's stop condition leans on them.
- Don't hardcode eval answers into the proposed harness/gates.
- If the repo genuinely has no inferable entry (no scripts/routes/main), THEN ask the user how the
  agent is invoked.
