# Adapter Typing — Design

- **Date:** 2026-06-24
- **Status:** Approved (brainstormed), pending implementation plan
- **Project:** `loop-iteration` (the `self-iterate` plugin)
- **Builds on:** [Plugin-ization design](2026-06-23-plugin-ization-design.md) (already implemented on `main`, 40 tests green)

## 1. Goal & motivation

The plugin-ization made Claude-Code-native agents zero-config (generic `claude -p` adapter). But the
dogfood on `maas-customer-agent` exposed the boundary: maas is a **tool-using service/in-process agent**,
so a standalone `claude -p` hangs on it. Today the only escape is a full custom `run_case.py` — which,
for the whole class of non-`claude -p` agents, is recurring per-agent code.

The goal: turn "how do I invoke my agent on a case?" from **per-agent code** into **declarative config**
for the common patterns. Add built-in adapter **types** selected by `agent.type` in `goal.yaml`; keep
`run_case.py` as the final bespoke escape hatch.

**Honest framing on config-vs-code:**
- Standard-CLI agents → `command` type, **zero code**.
- In-process agents like maas → `python-import` type, **one tiny standard shim** (~5-line `entry`), because
  the plugin can't make them zero-code without the agent exposing a standard interface.
- Truly bespoke → `run_case.py` (unchanged).

## 2. Key decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| T1 | **v1 types: `claude-p` + `command` + `python-import` (+ `run_case.py` escape hatch); `http` deferred** | `command` covers CLI agents (common, zero-code); `python-import` covers in-process agents like maas (the demo's pattern). `http`'s variant-application to a live service is messy (per-request skills_dir vs per-variant restart) — defer to keep v1 focused; `run_case.py` covers bespoke http for now. |
| T2 | **Dispatch via an `adapter_factory` switching on `agent.type`** | Matches the current `run_case` seam; one function in `adapter_generic` per type; `apply_variant`/`snapshot`/scoring/goal-check stay fully shared and unchanged. Minimal, no class-registration machinery. |
| T3 | **`apply_variant` (worktree) unchanged; the type only governs `run_case` + variant application** | The worktree holds the variant harness for every type. `claude-p` runs in it; `command`/`python-import` receive `variant_dir` (= worktree, or `worktree/<variant_subdir>`) and apply it. apply_variant stays generic. |

## 3. Design

### 3.1 The type system + dispatch

`agent.type` in `goal.yaml` selects how a case is run. `build_run_case(eval_dir, agent_config) ->
run_case_fn` returns a `run_case_fn(case, worktree)` based on the type. `apply_variant`/`snapshot`
unchanged.

```
goal.yaml `agent:`                what the plugin does per case
─────────────────────────────────────────────────────────────────────
type: claude-p   (default)        claude -p "<query>" in the worktree (cwd = variant)
type: command                     run cmd with {variant_dir}/{query}/{worktree} substituted; capture stdout
type: python-import               import <module>; call <entry>(query, variant_dir, **extra); return str|dict
type: custom  /  omitted          load the user's run_case.py (escape hatch — unchanged)
```

### 3.2 Each type's config schema + contract

**`claude-p`** (default — unchanged, gains an explicit `type`):
```yaml
agent:
  type: claude-p            # optional — it's the default
  model: claude-haiku-4-5-20251001
  permission_mode: bypassPermissions
  timeout: 120
```

**`command`** — run a CLI with placeholders substituted:
```yaml
agent:
  type: command
  cmd: ["python", "-m", "src.agent.cli", "--skills-dir", "{variant_dir}", "{query}"]
  variant_subdir: skills    # optional: {variant_dir} = worktree/variant_subdir (default = worktree)
  timeout: 120
```
The plugin runs `cmd`, captures stdout as the answer. Zero user code if the agent has a CLI that accepts
a skills-dir/harness path + a query.

**`python-import`** — import a module, call an entry with the variant dir:
```yaml
agent:
  type: python-import
  module: maas_entry               # a module the user provides
  module_path: ["."]               # optional: dir(s) (relative to cwd = user repo) added to sys.path so `module` imports
  entry: run                        # function in the module
  variant_subdir: skills            # optional: variant_dir = worktree/variant_subdir (default = worktree)
  extra: { channel: qiyu }          # optional: extra kwargs forwarded to entry
  timeout: 120
```
The plugin adds each `module_path` entry (resolved relative to the current working dir) to `sys.path`,
imports `module`, calls
`entry(query=<case.query>, variant_dir=<worktree>/<variant_subdir>, **extra)`. The entry returns a `str`
(answer) or a rich `{output, trace, error}` dict; `_normalize_result` converts to a `Result`. Never raises
(caught → `error` field).

**The maas shim** (the whole per-agent code, ~5 lines, standard signature):
```python
# maas_entry.py  (lives anywhere on module_path)
def run(query, variant_dir, channel="qiyu"):
    from src.agent import MaasAgentRunner          # maas's in-process entrypoint
    agent = MaasAgentRunner(skills_dir=variant_dir) # apply the variant harness
    return agent.run(query, channel=channel)         # answer string
```

**`custom` / `run_case.py`** (escape hatch — unchanged): if `type` is `custom` or omitted, load the user's
`run_case.py` exactly as today.

### 3.3 Variant application per type

- **claude-p**: the worktree IS the agent's context (claude runs in it). Zero config.
- **command**: `{variant_dir}` in `cmd` is substituted with the worktree path (optionally + `variant_subdir`),
  so the agent reads its variant harness from there. Zero user code if the agent has a CLI.
- **python-import**: `variant_dir` is passed to the entry function, which applies it (e.g. `skills_dir=variant_dir`).

The factory keeps `apply_variant`/`snapshot`/scoring/goal-check fully shared — a type only contributes the
`run_case` closure.

### 3.4 Dispatch precedence (backward-compatible)

- `type: claude-p | command | python-import` → that type.
- `type: custom` or `type` omitted + a `run_case.py` present → `run_case.py` (escape hatch).
- `type` omitted + no `run_case.py` → `claude-p` default.

Existing toy (no type, no run_case.py) stays claude-p; existing escape-hatch users (run_case.py, no type)
stay on run_case.py. Nothing breaks.

## 4. Implementation mapping, tests, scope

**Changes (all in `scripts/loop_iter/`):**

| Unit | Change |
|---|---|
| `adapter_generic.py` | **New `build_run_case(eval_dir, agent_config) -> run_case_fn`** (factory; switches on `agent_config["type"]`). **New `run_command_case`** (cmd template + `{variant_dir}`/`{query}`/`{worktree}` substitution, subprocess, never raises). **New `run_python_import_case`** (sys.path setup, import module, call `entry(query, variant_dir, **extra)`, normalize). **New `_normalize_result`** (str or `{output,trace,error}` dict → Result). `run_case_default`/`build_agent_cmd`/`load_run_case`/`resolve_harness`/`snapshot_harness` unchanged. |
| `cli.py` `_case_run` | Replace the inline run_case resolution with `rc = build_run_case(args.eval, goal.get("agent", {}))`. The factory owns all dispatch + the run_case.py fallback. |

**Tests (TDD):** `run_command_case` with a fake echo command + substitution; `run_python_import_case` with a
fake entry module returning a str and returning a rich dict (variant_dir passed correctly); `build_run_case`
dispatch per type + run_case.py fallback + claude-p default + clear error on unknown type; `_normalize_result`
str/dict. Existing 40 tests stay green.

**Docs:** brief `agent.type` reference added to the README plugin section; `examples/toy` stays claude-p.

**Scope (YAGNI):**
- **In:** factory + `command` + `python-import` + `_normalize_result`; cli wiring; tests; brief doc update.
  `claude-p` and `run_case.py` behavior unchanged.
- **Out (explicitly):** the `http` type (deferred); **the live maas dogfood run** (separate step after this
  lands — write `maas_entry.py` + a maas eval spec, then run with an OPENAI key; partly lives in the maas repo).
  The plan stages the maas shim/eval as the validation artifact; the live scored loop needs the user's key.

## 5. Open questions / future

- **`http` type (v2)** — for agents exposed as a queryable HTTP service. Needs a clean variant-application
  story (service supports a per-request skills_dir/header, or a documented per-variant restart). Until then,
  bespoke http agents use `run_case.py`.
- **Live maas validation** — after this lands: write `maas_entry.py` + a `support-tone` eval spec (reuse the
  demo's qa cases), run a real round with an OPENAI key. This is the proof that maas integrates via a ~5-line
  shim instead of a 70-line adapter.
