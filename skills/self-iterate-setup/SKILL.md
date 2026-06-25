---
name: self-iterate-setup
description: Interactive setup for the self-iterate loop. Reads the current repo, detects the agent's entry type, asks the user for the optimization goal, proposes a complete eval spec (goal.yaml/cases.json/gates.py/judge.md/quality.md + the adapter's entry file), confirms each piece, writes it to .self-iterate/<goal>/, self-validates via cli `validate-spec`, then resolves the Python env via cli `setup`. Use when the user runs "/self-iterate setup".
---

# self-iterate-setup (interactive)

You bootstrap a self-iterate eval spec for the agent in the user's current repo (cwd), then resolve
its Python env. PROPOSE drafts and CONFIRM each with the user before writing — never silently invent
an optimization target.

The flow: read the user's repo to detect the agent's kind → pick the matching adapter below → fill
its `agent:` config from what you read (writing the shim / `adapter.py` where the template shows) →
propose the eval spec → write all required files → run `setup`, `validate-spec`, `smoke`. The
adapter contracts below are complete — copy/adapt them from the user's code.

Investigate-first: read the user's repo to infer + propose every config value; the user confirms or
tweaks. Reserve open-ended questions for the GOAL (user intent) and WHICH agent when several exist.

## Adapter wiring

Pick the adapter by the agent's kind. Each entry is the complete `agent:` block for goal.yaml plus
any script to write. Copy/adapt it from the user's code.

| Agent kind | `agent.type` | extra file to write? |
|---|---|---|
| Claude-Code-native (CLAUDE.md / .claude/skills) | `claude-p` (default, omit type) | none |
| Has a CLI (`python -m …`, a bin script) | `command` | none |
| In-process Python module (importable) | `python-import` | entry shim (write) |
| Local HTTP service, simple JSON POST + JSON answer | `local-service` | none |
| Local HTTP service, bespoke (SSE / JWT / custom events) | `custom` | `adapter.py` (write) |

### claude-p — Claude-Code-native agent
```yaml
agent:
  model: claude-haiku-4-5-20251001      # optional
  permission_mode: bypassPermissions     # optional
  timeout: 120                           # optional
```
`harness:` = the files the agent reads (CLAUDE.md, AGENTS.md, .claude/skills/**/*.md, .claude/agents/**/*.md).

### command — agent has a CLI
```yaml
agent:
  type: command
  cmd: ["python", "-m", "my_agent", "--skills-dir", "{variant_dir}", "{query}"]
  variant_subdir: skills                 # optional: harness lives under worktree/<sub>
```
`{variant_dir}` = the worktree (or worktree/<variant_subdir>); `{query}` = the case query. The CLI
must read its harness from `{variant_dir}`. `harness:` = those files.

### python-import — in-process Python module (write a shim)
```yaml
agent:
  type: python-import
  module: my_entry                       # the shim module name (file: my_entry.py)
  entry: run                             # function signature: run(query, variant_dir, **extra)
  module_path: [".", ".self-iterate/<goal>"]   # dirs to find the shim + the agent package
  venv: .venv                            # venv with the agent's deps (detect .venv/venv/uv)
  variant_subdir: skills                 # optional
```
Write `.self-iterate/<goal>/my_entry.py`. Read the agent's construction code and replicate how it's
normally built, swapping `skills_dir=variant_dir` so the variant harness applies:
```python
def run(query, variant_dir, **extra):
    # build the agent with skills_dir=variant_dir (the variant harness), run the query,
    # return the answer text — or a dict {output, trace, error}. Never raise (use error field).
    ...
```
`harness:` = the skills the shim wires to `variant_dir` (e.g. `skills/**/*.md`). Anything the shim
imports via `module_path` (e.g. a system prompt) loads from the repo, NOT the worktree — so
`harness:` is ONLY the files the shim wires to `variant_dir`.

### local-service — local HTTP, simple JSON POST + JSON answer
```yaml
agent:
  type: local-service
  start: ["bash", "-c", "cd {worktree} && <launch the service> --port {port}"]
  port: 0                                # 0 = auto free port
  ready: "http://localhost:{port}/health"          # polled until HTTP <500 (optional but recommended)
  endpoint: "http://localhost:{port}/v1/chat"
  request: '{"query":"{query}"}'         # POST body template; {query} substituted
  response_path: "data.answer"           # dotted JSON path to the answer text
  timeout: 120
```
The service starts FROM the worktree each round (`{worktree}` substituted, cwd=worktree), so it
loads the variant harness — it must read its harness from its launch dir. `harness:` = those files.

### custom — local HTTP, bespoke protocol (SSE / JWT / custom events)
```yaml
agent:
  type: custom
```
Write `.self-iterate/<goal>/adapter.py`. The plugin calls `start` once per round, `run_case` per
case, `stop` in finally. `start`'s return value is ignored — stash any state `run_case` needs
(port, auth token) in module globals.
```python
# adapter.py — bespoke protocol. Read the agent's route handler / SSE encoder / auth module.
_port = None
def start(worktree):
    # launch the real service FROM the worktree (variant harness applies). Stash state in globals.
    global _port
    _port = ...   # e.g. pick a free port, subprocess the service with cwd=worktree
def run_case(case, worktree):
    # call the endpoint with the protocol's auth/headers, parse the bespoke response (SSE events,
    # etc.) into the answer. Never raise -> return error field.
    return {"case_id": case["id"], "output": <answer>, "trace": {}, "error": None}
def stop():
    # kill the service. Never raises.
```
`harness:` = the files the service reads from its launch dir.

## Required files

Write every one of these to `.self-iterate/<goal>/` (none may be missing):
- `goal.yaml` — `threshold`, `max_rounds`, `regression: block`, `weights` (gates heavy + ≥1 judge
  dim), `agent:` (from the adapter section above), `harness:` (only files that reach the agent),
  `quality_tolerance: 0.5`.
- `cases.json` — non-empty list of `{id, query, expected?}` (3-6 cases probing the goal).
- `gates.py` — `GATES = {name: fn}` where `fn(result, case) -> {"passed": bool}`, reading
  `result["output"]`. Programmatic + verifiable.
- `judge.md` — 1-2 LLM-rubric dims (0-10) scoring the agent's OUTPUT.
- `quality.md` — harness-quality rubric: clarity / no_overfit (auto-detected) / maintainability.
- the adapter's extra file — the entry shim (`python-import`) or `adapter.py` (`custom`), if the
  type needs one. (claude-p / command / local-service need none.)

## Workflow

1. **Read the user's repo.** Detect the agent's kind + harness + entry: harness candidates
   (CLAUDE.md, AGENTS.md, .claude/skills, skills/, src/prompts), entry signals (pyproject scripts,
   a CLI, an importable module, a local HTTP service / FastAPI route). List the agents if several.
   Note an existing `.self-iterate/<goal>/` (ask reuse/overwrite).

2. **Pick the adapter** from the table by the agent's kind. Read the user's code to fill the
   `agent:` block (and write the shim/adapter.py where the template shows). CONFIRM the choice.

3. **Ask the goal.** Confirm WHICH agent (if several — don't default), then ask the optimization
   target (user intent). Propose a kebab-case `<goal>` dir name; CONFIRM.

4. **Propose the eval spec** from the templates above (goal.yaml/cases.json/gates.py/judge.md/
   quality.md + the adapter file). CONFIRM each file before writing.

5. **Write ALL required files** to `.self-iterate/<goal>/`.

6. **Resolve the Python env:**
   ```
   python <plugin>/scripts/loop_iter/cli.py setup --eval .self-iterate/<goal>
   ```
   Picks `agent.venv` if set else bootstraps `.self-iterate/.venv`; records `.self-iterate/.python`.

7. **Validate + smoke** under the recorded interpreter:
   ```
   "$(cat .self-iterate/.python)" <plugin>/scripts/loop_iter/cli.py validate-spec --eval .self-iterate/<goal>
   "$(cat .self-iterate/.python)" <plugin>/scripts/loop_iter/cli.py smoke --eval .self-iterate/<goal>
   ```
   Fix problems until `validate-spec` is valid and `smoke` runs case[0] without error (for
   local-service/custom it starts the service, calls case[0], stops). Only then is setup done.

8. **Report.** Spec ready at `.self-iterate/<goal>/`; next step `/self-iterate start <goal>`.

## Rules
- Produce ALL required files — none may be missing.
- Investigate-first: infer + propose every config from the user's code; the user confirms/tweaks.
- PROPOSE then CONFIRM. Never write without the user confirming the goal + each file.
- Gates must be programmatic + verifiable (a boolean), not LLM vibes.
- Don't hardcode eval answers into the proposed harness/gates.
- `harness:` = ONLY files that actually reach the agent for the chosen adapter (see each section).
