# Adapter Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add built-in adapter **types** (`command`, `python-import`) selected by `agent.type` in `goal.yaml`, so non-`claude -p` agents (like maas) integrate via declarative config or a tiny standard shim instead of a full custom `run_case.py`.

**Architecture:** A `build_run_case(eval_dir, agent_config, harness)` factory in `adapter_generic.py` switches on `agent.type` and returns a `run_case_fn(case, worktree)`. New `run_command_case` (CLI + `{variant_dir}`/`{query}` substitution) and `run_python_import_case` (import module, call `entry(query, variant_dir, **extra)`). `apply_variant`/`snapshot`/scoring/goal-check unchanged. `claude-p` stays default; `run_case.py` stays the fallback.

**Tech Stack:** Python 3.11+, pytest, subprocess, importlib.

**Spec:** [docs/superpowers/specs/2026-06-24-adapter-typing-design.md](../specs/2026-06-24-adapter-typing-design.md)

---

## File Structure

```
scripts/loop_iter/
├── adapter_generic.py   MODIFY — add _variant_dir, _sub, _normalize_result, run_command_case,
│                                   run_python_import_case, build_run_case (existing fns unchanged)
└── cli.py               MODIFY — _case_run resolves run_case via build_run_case (not inline)
tests/
└── test_adapter_generic.py  APPEND — tests for the new fns + factory dispatch
README.md                MODIFY — add the agent.type reference table
```

**Signatures (consistent across tasks):**
- `_variant_dir(worktree, config) -> str`, `_sub(template, mapping) -> str`, `_normalize_result(raw, case_id) -> Result`.
- `run_command_case(case, worktree, config) -> Result`, `run_python_import_case(case, worktree, config) -> Result`.
- `build_run_case(eval_dir, agent_config, harness) -> callable` returning `run_case_fn(case, worktree)`.
- `Result = {"case_id": str, "output": str, "trace": dict, "error": str|None}`.

---

## Task 1: Helpers — `_variant_dir`, `_sub`, `_normalize_result`

**Files:**
- Modify: `scripts/loop_iter/adapter_generic.py` (append helpers)
- Test: `tests/test_adapter_generic.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_adapter_generic.py`:**

```python
from loop_iter.adapter_generic import _variant_dir, _sub, _normalize_result


def test_variant_dir_default_is_worktree(tmp_path):
    assert _variant_dir(str(tmp_path), {}) == str(tmp_path)


def test_variant_dir_with_subdir(tmp_path):
    assert _variant_dir(str(tmp_path), {"variant_subdir": "skills"}) == str(tmp_path / "skills")


def test_sub_replaces_placeholders():
    out = _sub("echo {query} in {variant_dir}",
               {"{query}": "hi", "{variant_dir}": "/wt"})
    assert out == "echo hi in /wt"


def test_normalize_result_from_str():
    r = _normalize_result("hello", "c1")
    assert r == {"case_id": "c1", "output": "hello", "trace": {}, "error": None}


def test_normalize_result_from_none():
    r = _normalize_result(None, "c1")
    assert r["output"] == "" and r["error"] is None


def test_normalize_result_from_rich_dict():
    r = _normalize_result({"output": "hi", "trace": {"x": 1}, "error": "boom"}, "c1")
    assert r == {"case_id": "c1", "output": "hi", "trace": {"x": 1}, "error": "boom"}
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → expect FAIL (`ImportError: cannot import name _variant_dir ...`).

- [ ] **Step 3: Append to `scripts/loop_iter/adapter_generic.py`:**

```python
import os


def _variant_dir(worktree: str, config: dict) -> str:
    """The variant harness dir: worktree itself, or worktree/<variant_subdir>."""
    sub = config.get("variant_subdir")
    return os.path.join(worktree, sub) if sub else worktree


def _sub(template: str, mapping: dict) -> str:
    """Substitute {variant_dir}/{query}/{worktree}-style placeholders in a string."""
    out = template
    for k, v in mapping.items():
        out = out.replace(k, str(v))
    return out


def _normalize_result(raw, case_id: str) -> dict:
    """Coerce an entry's return (str | None | {output,trace,error}) into a Result."""
    if isinstance(raw, dict) and "output" in raw:
        return {"case_id": case_id, "output": str(raw.get("output", "")),
                "trace": raw.get("trace") or {}, "error": raw.get("error")}
    return {"case_id": case_id, "output": str(raw) if raw is not None else "",
            "trace": {}, "error": None}
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → expect `11 passed` (3 existing resolve_harness + 8 new... adjust to whatever the count is; the 8 new pass). Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/adapter_generic.py tests/test_adapter_generic.py
git commit -m "feat: add adapter helpers (_variant_dir, _sub, _normalize_result)"
```

---

## Task 2: `run_command_case`

**Files:**
- Modify: `scripts/loop_iter/adapter_generic.py` (append)
- Test: `tests/test_adapter_generic.py` (append)

- [ ] **Step 1: Append failing tests:**

```python
import sys
from loop_iter.adapter_generic import run_command_case


def test_run_command_case_substitutes_query(tmp_path):
    # cmd = [python, -c, "print uppercased argv[1]", {query}]
    cmd = [sys.executable, "-c", "import sys; print(sys.argv[1].upper())", "{query}"]
    r = run_command_case({"id": "c1", "query": "hello", "expected": None},
                         str(tmp_path), {"cmd": cmd})
    assert r["case_id"] == "c1"
    assert r["output"].strip() == "HELLO"
    assert r["error"] is None


def test_run_command_case_uses_variant_subdir(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "marker").write_text("VARIANT")
    cmd = [sys.executable, "-c", "print(open(sys.argv[1]).read())", "{variant_dir}/marker"]
    r = run_command_case({"id": "c1", "query": "q", "expected": None},
                         str(tmp_path), {"cmd": cmd, "variant_subdir": "skills"})
    assert r["output"].strip() == "VARIANT"


def test_run_command_case_never_raises_on_bad_cmd(tmp_path):
    r = run_command_case({"id": "c1", "query": "q", "expected": None},
                         str(tmp_path), {"cmd": ["/no/such/binary"], "timeout": 5})
    assert r["error"] is not None
    assert r["output"] == ""
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → expect FAIL (`ImportError: cannot import name run_command_case`).

- [ ] **Step 3: Append to `scripts/loop_iter/adapter_generic.py`:**

```python
def run_command_case(case: dict, worktree: str, config: dict) -> dict:
    """Run config['cmd'] with {variant_dir}/{query}/{worktree} substituted; capture stdout.
    Never raises (crash/timeout -> error field)."""
    variant_dir = _variant_dir(worktree, config)
    mapping = {"{variant_dir}": variant_dir,
               "{query}": case.get("query", ""),
               "{worktree}": worktree}
    cmd = [_sub(str(t), mapping) for t in config.get("cmd", [])]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=config.get("timeout", 120))
        output = proc.stdout.strip()
        error = None if proc.returncode == 0 else f"exit {proc.returncode}: {proc.stderr.strip()[:300]}"
    except Exception as exc:
        output, error = "", f"run_case error: {exc!r}"
    return {"case_id": case["id"], "output": output, "trace": {}, "error": error}
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → the 3 new tests pass. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/adapter_generic.py tests/test_adapter_generic.py
git commit -m "feat: add run_command_case adapter (CLI + {variant_dir}/{query} substitution)"
```

---

## Task 3: `run_python_import_case`

**Files:**
- Modify: `scripts/loop_iter/adapter_generic.py` (append)
- Test: `tests/test_adapter_generic.py` (append)

- [ ] **Step 1: Append failing tests:**

```python
import sys
from loop_iter.adapter_generic import run_python_import_case


def _write_entry(tmp_path, name, body):
    (tmp_path / f"{name}.py").write_text(body)
    return name


def test_run_python_import_case_str_return(tmp_path):
    name = _write_entry(tmp_path, "ent_str",
        "def run(query, variant_dir, **extra):\n    return query.upper() + '@' + variant_dir\n")
    r = run_python_import_case({"id": "c1", "query": "hi", "expected": None},
                               str(tmp_path), {"module": name, "module_path": [str(tmp_path)],
                                               "variant_subdir": "skills"})
    assert r["output"] == "hi@" + str(tmp_path / "skills")
    assert r["error"] is None


def test_run_python_import_case_rich_dict_return(tmp_path):
    name = _write_entry(tmp_path, "ent_dict",
        "def run(query, variant_dir, **extra):\n    return {'output':'ok','trace':{'k':1},'error':None}\n")
    r = run_python_import_case({"id": "c1", "query": "q", "expected": None},
                               str(tmp_path), {"module": name, "module_path": [str(tmp_path)]})
    assert r["output"] == "ok" and r["trace"] == {"k": 1}


def test_run_python_import_case_forwards_extra_kwargs(tmp_path):
    name = _write_entry(tmp_path, "ent_extra",
        "def run(query, variant_dir, channel='x', **_):\n    return channel\n")
    r = run_python_import_case({"id": "c1", "query": "q", "expected": None},
                               str(tmp_path), {"module": name, "module_path": [str(tmp_path)],
                                               "extra": {"channel": "qiyu"}})
    assert r["output"] == "qiyu"


def test_run_python_import_case_never_raises(tmp_path):
    name = _write_entry(tmp_path, "ent_boom", "def run(query, variant_dir, **_):\n    raise RuntimeError('x')\n")
    r = run_python_import_case({"id": "c1", "query": "q", "expected": None},
                               str(tmp_path), {"module": name, "module_path": [str(tmp_path)]})
    assert r["error"] is not None and r["output"] == ""
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → expect FAIL (`ImportError: cannot import name run_python_import_case`).

- [ ] **Step 3: Append to `scripts/loop_iter/adapter_generic.py`:**

```python
import importlib


def run_python_import_case(case: dict, worktree: str, config: dict) -> dict:
    """Import config['module'] (after adding config['module_path'] to sys.path), call
    config['entry'](query=, variant_dir=, **extra); normalize the return. Never raises."""
    variant_dir = _variant_dir(worktree, config)
    for p in config.get("module_path", []):
        ap = os.path.abspath(p)
        if ap not in sys.path:
            sys.path.insert(0, ap)
    try:
        mod = importlib.import_module(config["module"])
        entry = getattr(mod, config.get("entry", "run"))
        raw = entry(query=case.get("query", ""), variant_dir=variant_dir,
                    **(config.get("extra") or {}))
        return _normalize_result(raw, case["id"])
    except Exception as exc:
        return {"case_id": case["id"], "output": "", "trace": {}, "error": f"run_case error: {exc!r}"}
```

(`sys` is already imported at the top of `adapter_generic.py` from the resolve_harness/load_run_case additions; if not, add `import sys` here.)

- [ ] **Step 4:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → the 4 new tests pass. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/adapter_generic.py tests/test_adapter_generic.py
git commit -m "feat: add run_python_import_case adapter (import + entry(query, variant_dir, **extra))"
```

---

## Task 4: `build_run_case` factory (dispatch)

**Files:**
- Modify: `scripts/loop_iter/adapter_generic.py` (append)
- Test: `tests/test_adapter_generic.py` (append)

- [ ] **Step 1: Append failing tests:**

```python
import sys
from loop_iter.adapter_generic import build_run_case


def test_factory_command_type(tmp_path):
    cmd = [sys.executable, "-c", "import sys; print(sys.argv[1].upper())", "{query}"]
    rc = build_run_case(str(tmp_path), {"type": "command", "cmd": cmd}, [])
    r = rc({"id": "c1", "query": "hi", "expected": None}, str(tmp_path))
    assert r["output"].strip() == "HI"


def test_factory_claude_p_type_returns_default_runner(tmp_path):
    rc = build_run_case(str(tmp_path), {"type": "claude-p"}, [])
    # claude-p default: with no real claude, it must still not raise (returns error field)
    r = rc({"id": "c1", "query": "q", "expected": None}, str(tmp_path))
    assert r["case_id"] == "c1" and r["error"] is not None  # no claude binary in test


def test_factory_omitted_type_with_run_case_py_uses_escape_hatch(tmp_path):
    (tmp_path / "run_case.py").write_text(
        "def run_case(case, worktree, harness):\n"
        "    return {'case_id': case['id'], 'output': 'ESCAPE', 'trace': {}, 'error': None}\n")
    rc = build_run_case(str(tmp_path), {}, ["CLAUDE.md"])
    r = rc({"id": "c1", "query": "q", "expected": None}, "/tmp")
    assert r["output"] == "ESCAPE"


def test_factory_omitted_type_without_run_case_py_falls_back_to_claude_p(tmp_path):
    rc = build_run_case(str(tmp_path), {}, [])
    r = rc({"id": "c1", "query": "q", "expected": None}, str(tmp_path))
    assert r["error"] is not None  # no claude binary -> error, but did not raise


def test_factory_unknown_type_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        build_run_case(str(tmp_path), {"type": "http"}, [])
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → expect FAIL (`ImportError: cannot import name build_run_case`).

- [ ] **Step 3: Append to `scripts/loop_iter/adapter_generic.py`:**

```python
_KNOWN_TYPES = {"claude-p", "command", "python-import", "custom"}


def build_run_case(eval_dir: str, agent_config: dict | None, harness: list):
    """Return a run_case_fn(case, worktree) chosen by agent_config['type'].

    Precedence: command | python-import | claude-p -> that type. custom/omitted ->
    run_case.py if present, else claude-p default. Unknown type -> ValueError.
    """
    cfg = agent_config or {}
    atype = cfg.get("type")
    if atype == "command":
        return lambda case, worktree: run_command_case(case, worktree, cfg)
    if atype == "python-import":
        return lambda case, worktree: run_python_import_case(case, worktree, cfg)
    if atype == "claude-p":
        return lambda case, worktree: run_case_default(case, worktree, cfg)
    if atype is not None and atype not in _KNOWN_TYPES:
        raise ValueError(f"unknown agent.type {atype!r}; expected one of {sorted(_KNOWN_TYPES)} or omit")
    # atype is None or "custom": escape hatch if present, else claude-p default
    user_rc = load_run_case(eval_dir)
    if user_rc is not None:
        return lambda case, worktree: user_rc(case, worktree, harness)
    return lambda case, worktree: run_case_default(case, worktree, cfg)
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_adapter_generic.py -q` → the 5 new tests pass. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/adapter_generic.py tests/test_adapter_generic.py
git commit -m "feat: add build_run_case factory (type dispatch + run_case.py fallback)"
```

---

## Task 5: Wire `cli.py` `_case_run` to `build_run_case`

**Files:**
- Modify: `scripts/loop_iter/cli.py` (the `_case_run` function)

- [ ] **Step 1: Replace the `_case_run` function in `scripts/loop_iter/cli.py` with:**

```python
def _case_run(args):
    import yaml
    from loop_iter.state import RunPaths, append_round
    from loop_iter.case_runner import run_cases
    from loop_iter.adapter_generic import resolve_harness, build_run_case
    ev = Path(args.eval)
    goal = yaml.safe_load((ev / "goal.yaml").read_text())
    cases = json.loads((ev / "cases.json").read_text())
    harness = resolve_harness(args.eval, args.base)
    rc = build_run_case(args.eval, goal.get("agent", {}), harness)
    from loop_iter.llm_client import chat as llm_call
    out = run_cases(cases, args.worktree, str(ev / "gates.py"),
                    (ev / "judge.md").read_text(), goal["weights"],
                    run_case_fn=rc, llm_call=llm_call)
    out["round"] = args.round
    rp = RunPaths(base=args.base, run_id=args.run_id)
    append_round(rp, out)
    print(json.dumps({"round": args.round, "composite": out["composite"],
                      "gate_pass_rates": out["gate_pass_rates"]}))
```

(This removes the inline `load_run_case`/`run_case_default` branching — now owned by `build_run_case` — so all four adapter types flow through one place.)

- [ ] **Step 2:** `.venv/bin/pytest -q` → full suite green (existing `test_cli.py` still passes; it exercises `goal-check` and `apply-variant`, not `_case_run`'s run_case resolution).

- [ ] **Step 3: Commit:**
```bash
git add scripts/loop_iter/cli.py
git commit -m "refactor: cli _case_run resolves run_case via build_run_case factory"
```

---

## Task 6: README `agent.type` reference

**Files:**
- Modify: `README.md` (add an `agent.type` subsection under the plugin section)

- [ ] **Step 1: In `README.md`, find the `### Use it on your agent` subsection and insert this block right after its code fence (before `Then:`):**

```markdown
#### Adapter type (`agent.type` in goal.yaml)

How each case is run against your agent — declarative, no code for the common cases:

| type | when | what you provide |
|---|---|---|
| `claude-p` (default) | Claude-Code-native agent | nothing (runs `claude -p` in the worktree) |
| `command` | agent has a CLI | `cmd` with `{variant_dir}`/`{query}` substituted, e.g. `["python","-m","src.agent.cli","--skills-dir","{variant_dir}","{query}"]` |
| `python-import` | in-process agent (e.g. maas) | `module` + `entry`; a ~5-line `entry(query, variant_dir, **extra)` shim that loads your agent with `skills_dir=variant_dir` |
| `custom` / omitted + `run_case.py` | bespoke | a drop-in `run_case.py` |

Example (`command`, zero code if your agent has a CLI):
\`\`\`yaml
agent:
  type: command
  cmd: ["python", "-m", "my_agent", "--skills-dir", "{variant_dir}", "{query}"]
  variant_subdir: skills
\`\`\`
```

(Render the inner yaml fence with real triple-backticks; the `\`\`\`` escapes above are only to avoid clashing with this plan's own fencing.)

- [ ] **Step 2:** Verify the README still renders (read back the inserted block). No tests affected.

- [ ] **Step 3: Commit:**
```bash
git add README.md
git commit -m "docs: add agent.type adapter reference to README"
```

---

## Self-Review (completed during authoring)

**1. Spec coverage:**
- §3.1 type system + dispatch → Task 4 (factory). ✓
- §3.2 `command` schema/contract → Task 2. ✓
- §3.2 `python-import` schema/contract (entry(query, variant_dir, **extra), normalize) → Task 3 + Task 1 (`_normalize_result`). ✓
- §3.2 `claude-p`/`custom` unchanged → Task 4 precedence (default + fallback) + Task 5 (cli delegates). ✓
- §3.3 variant application (`_variant_dir`) → Task 1. ✓
- §3.4 backward-compatible precedence → Task 4 (factory order + `_KNOWN_TYPES` + ValueError on unknown). ✓
- §4 impl mapping (factory in adapter_generic, cli wiring) + tests → Tasks 1–5. ✓
- §4 docs (README agent.type) → Task 6. ✓

**2. Placeholder scan:** No TBD/TODO. Every code step shows full code; Task 6's inner-fence escape is called out explicitly. The `test_factory_command_type` assertion line is a bit convoluted — replaced intent with a clean check below.

**3. Type consistency:** `build_run_case(eval_dir, agent_config, harness) -> run_case_fn(case, worktree)` is identical in Task 4 (def) and Task 5 (cli call). `run_command_case(case, worktree, config)`, `run_python_import_case(case, worktree, config)`, `_normalize_result(raw, case_id)`, `_variant_dir(worktree, config)`, `_sub(template, mapping)` are consistent across Tasks 1–4. `Result` shape (`case_id`/`output`/`trace`/`error`) matches the existing `run_case_default`.

**Fix applied inline:** `test_factory_command_type` — simplify the assertion to `assert r["output"].strip() == "HI"` (the cmd uppercases argv[1]="hi" → "HI"). The `HILO` artifact above was a typo; corrected here so the executor doesn't carry a broken assertion.
