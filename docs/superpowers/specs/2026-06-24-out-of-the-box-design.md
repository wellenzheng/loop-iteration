# Out-of-the-box `/self-iterate` on venv'd agents — Design

- **Date:** 2026-06-24
- **Status:** Approved (brainstormed), pending implementation plan
- **Project:** `loop-iteration` (the `self-iterate` plugin)
- **Builds on:** [Plugin-ization](2026-06-23-plugin-ization-design.md) + [Adapter typing](2026-06-24-adapter-typing-design.md)

## 1. Goal & motivation

Dogfooding on `maas-customer-agent` showed `/self-iterate` is **not** out-of-the-box for an agent
like maas: the `python-import` shim needs the agent's own deps (`zai_adk`), which the plugin's
bootstrapped `.self-iterate/.venv` lacks; and maas's `.env` (with `OPENAI_*` for both the agent and
the judge) can't be `source`d in zsh (a `&` on line 46 chokes it). So running the loop required a
hand-rolled wrapper that loaded `.env` and used maas's `.venv`.

The goal: make `/self-iterate` run on such agents with **no wrapper** — the plugin auto-loads `.env`
and runs the cli under the agent's own venv.

## 2. Key decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| B1 | **`.env` auto-load at cli startup**, shell-safe python parser, `setdefault` (never overrides existing env) | Removes the wrapper. `setdefault` keeps explicit env wins. Python parsing sidesteps zsh's choking on special chars in `.env`. |
| B2 | **`agent.venv` (dir path, relative to repo)** selects the interpreter; `setup` resolves it once + records `.self-iterate/.python`; skill/command invokes the cli with that interpreter | Explicit + cross-platform-ish (`<venv>/bin/python`). When omitted, `setup` bootstraps `.self-iterate/.venv` (current behavior, for venv-less agents). maas sets `agent.venv: .venv`. |

## 3. Design

### 3.1 `.env` auto-load (B1)

A `_load_dotenv(env_path=".env")` helper in `scripts/loop_iter/cli.py`, called at the top of `main()`:
- read `.env` from cwd (if present);
- for each non-comment, non-blank `KEY=VALUE` line: strip surrounding quotes from `VALUE`, then
  `os.environ.setdefault(KEY, VALUE)` (never overwrites an already-set var — explicit env wins);
- silently no-op if `.env` is absent.

All subcommands inherit it (harmless for `apply-variant`; `case-run`/`goal-check` need `OPENAI_*`).
This is exactly what the throwaway `/tmp/maas_cli.py` wrapper did — now built in.

### 3.2 Agent venv via `agent.venv` (B2)

`goal.yaml` gains an optional `agent.venv` (a venv directory, relative to the repo / cwd). The
`setup` subcommand (which gains an `--eval` arg so it can read the goal's `goal.yaml`) resolves the
interpreter **once** and records it at `.self-iterate/.python`:

- if `agent.venv` is set and `<venv>/bin/python` exists → use that interpreter; ensure `pyyaml` +
  `httpx` are installed in it (`<venv>/bin/pip install -q pyyaml httpx`, idempotent). The agent's
  own deps (e.g. `zai_adk`) are already there.
- else → bootstrap `.self-iterate/.venv` (`python -m venv`) + install `pyyaml`/`httpx`, use
  `.self-iterate/.venv/bin/python` (current behavior).
- write the chosen interpreter path to `.self-iterate/.python` (one line).

The `self-iterate` skill and the `/self-iterate` command then invoke the cli with that interpreter:
`PY=$(cat .self-iterate/.python 2>/dev/null || echo python); "$PY" <plugin>/scripts/loop_iter/cli.py …`.
So for maas (`agent.venv: .venv`), `/self-iterate toward support-escalation` runs the cli under
maas's venv (has `zai_adk`) with `.env` auto-loaded — out-of-the-box.

### 3.3 End-to-end for maas

`/self-iterate setup` (once) → resolves `.venv/bin/python`, installs pyyaml/httpx into maas's venv,
writes `.self-iterate/.python`. Then `/self-iterate toward support-escalation` → skill runs
`$(cat .self-iterate/.python) <plugin>/scripts/loop_iter/cli.py apply-variant|case-run|goal-check …`
→ cli auto-loads `.env` → shim imports `src.agent`/`zai_adk` (maas venv) + judge has `OPENAI_*`.
No wrapper, no manual `.env` sourcing.

## 4. Implementation mapping, tests, scope

**Changes (all small):**
- `scripts/loop_iter/cli.py`: add `_load_dotenv()` (called in `main`); rewrite `_setup` to resolve
  the interpreter from `goal.yaml`'s `agent.venv` (else bootstrap) and write `.self-iterate/.python`.
- `commands/self-iterate.md` + `skills/self-iterate/SKILL.md`: invoke the cli via `.self-iterate/.python`.
- `README.md`: note `agent.venv` + that `/self-iterate setup` picks the right interpreter.

**Tests (TDD):** `_load_dotenv` (parses KEY=VALUE; strips quotes; `setdefault` does NOT override an
already-set var; skips comments/blank; no-op when absent); `_setup` writes `.self-iterate/.python`
(uses `agent.venv` when set+exists; bootstraps `.self-iterate/.venv` when omitted). Existing 59 tests
stay green.

**Scope (YAGNI):** in = `.env` auto-load + `agent.venv` resolution + `.python` recording + skill/
command/README update + tests. Out = Windows venv layout (`Scripts\python.exe`); auto-detection of
`.venv` (explicit `agent.venv` only); loading config files other than `.env`.
