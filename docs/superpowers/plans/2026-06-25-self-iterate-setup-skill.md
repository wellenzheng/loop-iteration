# self-iterate setup skill — Implementation Plan (Plan 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/self-iterate setup` an interactive skill that reads the repo, proposes a complete eval spec (`goal.yaml`/`cases.json`/`gates.py`/`judge.md`/`quality.md`), confirms each piece with the user, writes it to `.self-iterate/<goal>/`, self-validates, then resolves the Python env — so the plugin is out-of-the-box (no hand-writing the spec).

**Architecture:** Two pieces. (1) A testable cli `validate-spec --eval <dir>` that statically checks a generated spec is well-formed (goal.yaml keys/types, cases.json structure, gates.py imports with a non-empty `GATES` dict of callables, judge.md non-empty, quality.md optional). (2) A `self-iterate-setup` **skill** (markdown) that drives the interactive workflow: read repo → detect agent type → ask goal → propose spec drafts → confirm each → write files → run `validate-spec` → run cli `setup`. The skill is LLM orchestration (not unit-testable); `validate-spec` is the testable safety net the skill calls to self-verify its output. The `/self-iterate setup` command dispatches the skill.

**Tech Stack:** Python 3.11+, pytest, stdlib `json`/`yaml`/`importlib`/`pathlib`.

**Spec basis:** [setup+loop spec](2026-06-24-self-iterate-setup-and-loop-design.md) §3.1 / D1.

---

## File Structure

```
scripts/loop_iter/validate_spec.py   CREATE — validate_spec(eval_dir) -> {valid, problems, warnings}
scripts/loop_iter/cli.py             MODIFY — add `validate-spec` subcommand
skills/self-iterate-setup/SKILL.md   CREATE — the interactive setup skill
commands/self-iterate.md             MODIFY — `/self-iterate setup` dispatches the skill
tests/test_validate_spec.py          CREATE — validate_spec tests
README.md                            MODIFY — note `/self-iterate setup` is interactive
```

**Signatures:**
- `validate_spec.validate_spec(eval_dir: str) -> dict` → `{"valid": bool, "problems": list[str], "warnings": list[str]}`. Problems are fatal (invalid spec); warnings are non-fatal (e.g. quality.md absent, agent.type unset → defaults).

**validate_spec checks:**
- `goal.yaml`: exists, parseable YAML, has `threshold` (number), `max_rounds` (int≥1), `weights` (non-empty dict). `regression`/`agent`/`harness`/`quality_tolerance` optional. → problem if missing/wrong type.
- `cases.json`: exists, valid JSON list, non-empty, each item a dict with `id` and `query`. → problem otherwise.
- `gates.py`: exists, importable (no SyntaxError), defines `GATES` as a non-empty dict of callables. → problem otherwise.
- `judge.md`: exists, non-empty. → problem otherwise.
- `quality.md`: optional. → warning if absent (guardrail inactive). If present, non-empty (else problem).
- `agent.type`: if set, must be one of `claude-p`/`command`/`python-import`/`custom` (warning if unset → defaults to claude-p). If `custom` or unset and no `run_case.py` → warning (will use claude-p default). If `command`, warn if no `agent.cmd`; if `python-import`, warn if no `agent.module`/`agent.entry`.

---

## Task 1: `validate_spec` + cli `validate-spec` subcommand

**Files:** Create `scripts/loop_iter/validate_spec.py`, Create `tests/test_validate_spec.py`, Modify `scripts/loop_iter/cli.py`

- [ ] **Step 1: Create `tests/test_validate_spec.py`:**

```python
import json
from pathlib import Path
from loop_iter.validate_spec import validate_spec


def _write_valid_spec(d: Path):
    (d / "goal.yaml").write_text(
        "threshold: 0.85\nmax_rounds: 3\nweights: {gates: 2.0, conciseness: 1.0}\nregression: block\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (d / "gates.py").write_text(
        "def g(result, case):\n    return {'passed': True}\nGATES = {'g': g}\n")
    (d / "judge.md").write_text("score conciseness 0-10")
    (d / "quality.md").write_text("clarity / no_overfit / maintainability")


def test_valid_spec(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    v = validate_spec(str(d))
    assert v["valid"] is True
    assert v["problems"] == []


def test_missing_goal_yaml(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "cases.json").write_text("[]")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("goal.yaml" in p for p in v["problems"])


def test_goal_yaml_bad_types(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: high\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text("[]")
    (d / "gates.py").write_text("GATES = {}")
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("threshold" in p for p in v["problems"])


def test_max_rounds_must_be_positive_int(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 0\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text("[]")
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("max_rounds" in p for p in v["problems"])


def test_cases_must_be_nonempty_list_with_id_query(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1"}]')  # missing query
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("query" in p for p in v["problems"])


def test_gates_py_must_define_GATES_dict_of_callables(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("GATES = {'g': 'not callable'}")  # value not callable
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("GATES" in p or "callable" in p for p in v["problems"])


def test_gates_py_syntax_error_is_problem(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("def broken(:\n")  # syntax error
    (d / "judge.md").write_text("x")
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("gates.py" in p for p in v["problems"])


def test_quality_md_optional_warning(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    (d / "goal.yaml").write_text("threshold: 0.5\nmax_rounds: 3\nweights: {gates: 1.0}\n")
    (d / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (d / "gates.py").write_text("GATES={'g':lambda r,c:{'passed':True}}")
    (d / "judge.md").write_text("x")
    # no quality.md
    v = validate_spec(str(d))
    assert v["valid"] is True
    assert any("quality.md" in w for w in v["warnings"])


def test_unknown_agent_type_warns(tmp_path):
    d = tmp_path / "g"; d.mkdir()
    _write_valid_spec(d)
    goal = (d / "goal.yaml").read_text() + "agent:\n  type: bogus\n"
    (d / "goal.yaml").write_text(goal)
    v = validate_spec(str(d))
    assert v["valid"] is False
    assert any("type" in p for p in v["problems"])
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_validate_spec.py -q` → expect FAIL (module missing).

- [ ] **Step 3: Create `scripts/loop_iter/validate_spec.py`:**

```python
"""Static validation of a .self-iterate/<goal>/ eval spec. The setup skill calls this after writing
the spec to self-verify; `validate-spec` cli wraps it. Problems are fatal (invalid spec); warnings
are non-fatal (optional pieces absent)."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path


_VALID_AGENT_TYPES = {"claude-p", "command", "python-import", "custom"}


def _load_gates(gates_path: Path):
    """Import gates.py and return its GATES dict, or raise. Used to catch syntax errors + shape."""
    spec = importlib.util.spec_from_file_location("_validate_gates", gates_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # raises SyntaxError / any import-time error
    return getattr(mod, "GATES", None)


def validate_spec(eval_dir: str) -> dict:
    """Return {'valid': bool, 'problems': [str], 'warnings': [str]} for the spec in eval_dir."""
    d = Path(eval_dir)
    problems: list[str] = []
    warnings: list[str] = []

    # goal.yaml
    goal_path = d / "goal.yaml"
    if not goal_path.exists():
        problems.append("goal.yaml: missing")
        goal = None
    else:
        try:
            import yaml
            goal = yaml.safe_load(goal_path.read_text()) or {}
        except Exception as e:
            problems.append(f"goal.yaml: unparseable ({e})")
            goal = {}
        if goal is not None:
            if not isinstance(goal.get("threshold"), (int, float)):
                problems.append("goal.yaml: threshold must be a number")
            mr = goal.get("max_rounds")
            if not isinstance(mr, int) or mr < 1:
                problems.append("goal.yaml: max_rounds must be a positive int")
            w = goal.get("weights")
            if not isinstance(w, dict) or not w:
                problems.append("goal.yaml: weights must be a non-empty dict")
            agent = goal.get("agent") or {}
            atype = agent.get("type")
            if atype is not None and atype not in _VALID_AGENT_TYPES:
                problems.append(f"goal.yaml: agent.type {atype!r} not in {sorted(_VALID_AGENT_TYPES)}")
            if atype is None:
                warnings.append("goal.yaml: agent.type unset -> defaults to claude-p")
            if atype == "command" and not agent.get("cmd"):
                warnings.append("goal.yaml: agent.type=command but no agent.cmd set")
            if atype == "python-import" and not (agent.get("module") and agent.get("entry")):
                warnings.append("goal.yaml: agent.type=python-import but agent.module/entry unset")

    # cases.json
    cases_path = d / "cases.json"
    if not cases_path.exists():
        problems.append("cases.json: missing")
    else:
        try:
            cases = json.loads(cases_path.read_text())
        except Exception as e:
            problems.append(f"cases.json: unparseable ({e})")
            cases = None
        if cases is not None:
            if not isinstance(cases, list) or not cases:
                problems.append("cases.json: must be a non-empty list")
            else:
                for i, c in enumerate(cases):
                    if not isinstance(c, dict) or "id" not in c or "query" not in c:
                        problems.append(f"cases.json: case #{i} must have 'id' and 'query'")

    # gates.py
    gates_path = d / "gates.py"
    if not gates_path.exists():
        problems.append("gates.py: missing")
    else:
        try:
            gates = _load_gates(gates_path)
        except Exception as e:
            problems.append(f"gates.py: failed to import ({e})")
            gates = None
        if gates is not None:
            if not isinstance(gates, dict) or not gates:
                problems.append("gates.py: GATES must be a non-empty dict")
            else:
                for name, fn in gates.items():
                    if not callable(fn):
                        problems.append(f"gates.py: GATES[{name!r}] is not callable")

    # judge.md
    judge_path = d / "judge.md"
    if not judge_path.exists() or not judge_path.read_text().strip():
        problems.append("judge.md: missing or empty")

    # quality.md (optional)
    qpath = d / "quality.md"
    if not qpath.exists():
        warnings.append("quality.md: absent -> quality guardrail inactive")
    elif not qpath.read_text().strip():
        problems.append("quality.md: empty")

    return {"valid": not problems, "problems": problems, "warnings": warnings}
```

- [ ] **Step 4: Add the `validate-spec` cli subcommand** in `scripts/loop_iter/cli.py`. Add the handler (near the other handlers):

```python
def _validate_spec(args):
    from loop_iter.validate_spec import validate_spec
    v = validate_spec(args.eval)
    print(json.dumps(v, indent=2, ensure_ascii=False))
    raise SystemExit(0 if v["valid"] else 1)
```

And register the subparser in `main()` (after the `report` subparser):

```python
    s = sub.add_parser("validate-spec")
    s.add_argument("--eval", required=True)
    s.set_defaults(func=_validate_spec)
```

- [ ] **Step 5:** `.venv/bin/pytest tests/test_validate_spec.py -q` → all pass. `.venv/bin/pytest -q` → full green.

- [ ] **Step 6: Commit:**
```bash
git add scripts/loop_iter/validate_spec.py scripts/loop_iter/cli.py tests/test_validate_spec.py
git commit -m "feat: validate-spec (static eval-spec well-formedness check)"
```

---

## Task 2: the `self-iterate-setup` skill

**Files:** Create `skills/self-iterate-setup/SKILL.md`

- [ ] **Step 1: Create `skills/self-iterate-setup/SKILL.md`:**

````markdown
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
````

- [ ] **Step 2:** No tests (skill doc). Run `.venv/bin/pytest -q` to confirm nothing broke.

- [ ] **Step 3: Commit:**
```bash
git add skills/self-iterate-setup/SKILL.md
git commit -m "feat: self-iterate-setup skill (interactive eval-spec scaffolding)"
```

---

## Task 3: wire `/self-iterate setup` command + README

**Files:** Modify `commands/self-iterate.md`, Modify `README.md`

- [ ] **Step 1: In `commands/self-iterate.md`**, the `## Usage` section currently lists `/self-iterate setup` as "(interactive proposer is a separate skill; until it lands, hand-write the spec...)". Update it to dispatch the now-existing skill. Replace the `setup` bullet with:

```markdown
- `/self-iterate setup` — interactive: dispatches the `self-iterate-setup` skill, which reads the
  repo, proposes the eval spec (goal.yaml/cases.json/gates.py/judge.md/quality.md), confirms each
  piece with you, writes it to `.self-iterate/<goal>/`, self-validates, then resolves the Python env
  (`agent.venv` or bootstrap) to `.self-iterate/.python`.
```

(Remove the "until it lands, hand-write..." parenthetical — the skill has landed. Keep the `start`/`toward` bullets and the rest.)

- [ ] **Step 2: In `README.md`**, the `### Install` section says `/self-iterate setup # picks the right Python...`. Update it to mention the interactive scaffolding. Replace that block with:

```markdown
/self-iterate setup        # interactive: reads the repo, proposes the eval spec (goal.yaml/cases.json/
                           # gates.py/judge.md/quality.md), confirms each with you, writes .self-iterate/<goal>/,
                           # self-validates, then resolves the Python env (agent.venv or bootstrap -> .self-iterate/.python).
```

And in the `### Use it on your agent` section, update the lead-in that says "write the only thing you need — an eval spec" to note setup now generates it:

```markdown
In your agent's repo, run `/self-iterate setup` — it proposes the eval spec for you to confirm. Or
hand-write it:
```

(Keep the eval-spec code block listing that follows.)

- [ ] **Step 3:** Run `.venv/bin/pytest -q` (docs only; confirm green).

- [ ] **Step 4: Commit:**
```bash
git add commands/self-iterate.md README.md
git commit -m "docs: /self-iterate setup dispatches the interactive setup skill"
```

---

## Self-Review

**1. Spec coverage (§3.1/D1):**
- setup is an interactive skill (not cli) → Task 2 (skill) + Task 3 (command dispatch). ✓
- reads repo, proposes spec, confirms, writes → Task 2 workflow steps 1-5. ✓
- self-validates → Task 1 (validate-spec) + Task 2 step 6. ✓
- resolves Python env (calls cli setup) → Task 2 step 7. ✓
- generates goal.yaml/cases.json/gates.py/judge.md/quality.md → Task 2 step 4. ✓

**2. Placeholders:** none; full code in Task 1; full skill doc in Task 2.

**3. Consistency:** `validate_spec(eval_dir) -> {valid, problems, warnings}` consistent (Task 1 def + tests + cli call). cli `validate-spec --eval <dir>` exits 0/1 (Task 1). The skill calls `validate-spec` then `setup` (Task 2 steps 6-7) — both cli commands exist. `agent.type` validation matches `adapter_generic._KNOWN_TYPES` (`claude-p`/`command`/`python-import`/`custom`). quality.md optional → warning (consistent with Plan 2's opt-in). ✓

**Testability note:** the skill itself (Task 2) is LLM orchestration and not unit-tested; `validate-spec` (Task 1) is the testable artifact and the skill's self-check. An end-to-end test of the skill would require driving Claude through the interactive flow — out of scope for this plan (covered by dogfooding).
