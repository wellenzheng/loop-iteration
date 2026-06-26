---
name: self-iterate-setup
description: Interactive setup for the self-iterate loop. Reads the current repo, detects the agent's entry type, asks the user for the optimization goal, proposes a complete eval spec (goal.yaml/cases.json/gates.py/rubric.md/quality.md + the adapter's entry file), confirms each piece, writes it to .self-iterate/<goal>/, self-validates via cli `validate-spec`, then resolves the Python env via cli `setup`. Use when the user runs "/self-iterate setup".
---

# self-iterate-setup (interactive)

You bootstrap a self-iterate eval spec for the agent in the user's current repo (cwd). Three phases:
**Confirm** (confirm each piece with the user) → **Prepare** (write all files) → **Verify** (verify
the agent is correctly callable). PROPOSE drafts and CONFIRM — never silently invent an optimization
target.

Investigate-first: read the user's repo to infer + propose every config value; the user confirms or
tweaks. Reserve open-ended questions for the GOAL (user intent) and WHICH agent when several exist.

## Adapter wiring

Pick the adapter by the agent's kind (step 2). Each entry is the complete `agent:` block for
goal.yaml plus any script to write. Copy/adapt it from the user's code.

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
  dim), `agent:` (from the adapter section), `harness:` (only files that reach the agent),
  `quality_tolerance: 0.5`, `quality_target` (optional float — enables the quality-judge auxiliary target).
- `cases.json` — non-empty list of `{id, query, expected?}` (3-6 cases probing the goal).
- `gates.py` — `GATES = {name: fn}` where `fn(result, case) -> {"passed": bool}`, reading
  `result["output"]`. Programmatic + verifiable.
- `rubric.md` — 1-2 LLM-rubric dims (0-10) scoring the agent's OUTPUT.
- `quality.md` — OPTIONAL supplementary context for the quality-judge (the quality-judge uses a
  built-in industry-standard 规范度 rubric by default; quality.md adds extra emphasis only).
- the adapter's extra file — the entry shim (`python-import`) or `adapter.py` (`custom`), if the
  type needs one. (claude-p / command / local-service need none.)

## Workflow

### Phase 1 · Confirm (with the user, item by item)

1. **Read the repo.** Skim the user's repo for the agent's harness + entry: harness candidates
   (CLAUDE.md, AGENTS.md, .claude/skills, skills/, src/prompts), entry signals (pyproject scripts,
   a CLI, an importable module, a local HTTP service / FastAPI route). List the agents if several;
   note an existing `.self-iterate/<goal>/` (ask reuse/overwrite).
2. **Confirm the agent type.** Match the agent to an adapter in the table above. CONFIRM the adapter
   choice + the `agent:` config with the user.
3. **Ask the goal.** Ask the optimization target (user intent — not inferable). Confirm WHICH agent
   if several (don't default). Propose a kebab-case `<goal>` dir name; CONFIRM.
4. **Ask the eval criteria (rubric).** Propose + CONFIRM the gates (programmatic, verifiable,
   reading `result["output"]`) and the judge dims (LLM 0-10 on the output). These become `gates.py`
   + `rubric.md`.
   - Ask whether to set `quality_target` (opt-in auxiliary target on harness 规范度 — when set, the
     loop also drives harness cleanup via a quality-judge sub-agent that scores against a BUILT-IN
     industry-standard 规范度 rubric, NOT a user quality.md; `met` then requires
     `quality ≥ quality_target`). If yes, add `quality_target: <float>` (recommend 8.0) to goal.yaml.
5. **Ask the eval entry.** Propose + CONFIRM how cases invoke the agent — the adapter entry (start
   cmd / endpoint+request / shim / adapter.py). Fill it by reading the user's code (see Adapter
   wiring). This is what step 7 writes.
6. **Ask the eval set (cases).** Ask the user where their eval data is (file path — may be
   `.csv` / `.json` / `.xlsx` / `.xls` with any column names). Ask which columns/fields map to
   `query` (required), `id` (optional, auto c1/c2/…), and `expected` (optional). Then adapt it to
   the standard format:
   ```
   python <plugin>/scripts/loop_iter/cli.py import-cases --from <user_file> --eval .self-iterate/<goal> --query-col <col> [--id-col <col>] [--expected-col <col>]
   ```
   This writes `cases.json` in the standard `[{id, query, expected?}]` format. If the user has no
   file, propose 3-6 cases from the goal. CONFIRM the generated cases.json with the user.

### Phase 2 · Prepare (produce all files)

7. **Adapt the agent.** Write the adapter so the agent is callable with the variant harness: the
   `agent:` block in goal.yaml + the shim (`python-import`) / `adapter.py` (`custom`) / start cmd
   (`local-service`), filled from the confirmed entry (step 5). Read the user's agent code to fill
   it.
8. **Adapt the eval data.** Write `cases.json`, `gates.py`, `rubric.md`, `quality.md`, `goal.yaml` —
   all matched to the confirmed goal + agent (Required files checklist — none missing).

### Phase 3 · Verify (can the agent be called correctly)

9. **Verify.** Resolve the env, static-check, then smoke-run one case to verify the agent is
   correctly callable with the variant harness:
   ```
   python <plugin>/scripts/loop_iter/cli.py setup --eval .self-iterate/<goal>
   "$(cat .self-iterate/.python)" <plugin>/scripts/loop_iter/cli.py validate-spec --eval .self-iterate/<goal>
   "$(cat .self-iterate/.python)" <plugin>/scripts/loop_iter/cli.py smoke --eval .self-iterate/<goal>
   ```
   Fix problems until `validate-spec` is valid AND `smoke` runs case[0] without error (for
   local-service/custom it starts the service, calls case[0], stops). Only then is setup done.

**Report.** Spec ready at `.self-iterate/<goal>/`; next step `/self-iterate start <goal>`.

## Rules
- Produce ALL required files — none may be missing.
- Investigate-first: infer + propose every config from the user's code; the user confirms/tweaks.
- PROPOSE then CONFIRM. Never write without the user confirming the goal + each file.
- Gates must be programmatic + verifiable (a boolean), not LLM vibes.
- Don't hardcode eval answers into the proposed harness/gates.
- `harness:` = ONLY files that actually reach the agent for the chosen adapter (see each section).
