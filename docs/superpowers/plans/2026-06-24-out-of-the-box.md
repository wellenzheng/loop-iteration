# Out-of-the-box `/self-iterate` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/self-iterate` run on venv'd agents like maas with no wrapper — the plugin auto-loads `.env` and runs the cli under the agent's own venv (`agent.venv`).

**Architecture:** `cli.py` gains `_load_dotenv()` (called in `main()`, `setdefault`) and a rewritten `setup` that resolves the interpreter from `goal.yaml`'s `agent.venv` (else bootstraps `.self-iterate/.venv`) and records it at `.self-iterate/.python`. The skill + command invoke the cli with that interpreter.

**Tech Stack:** Python 3.11+, pytest, stdlib `os`/`subprocess`/`pathlib`.

**Spec:** [docs/superpowers/specs/2026-06-24-out-of-the-box-design.md](../specs/2026-06-24-out-of-the-box-design.md)

---

## File Structure

```
scripts/loop_iter/cli.py   MODIFY — add _load_dotenv (called in main); rewrite _setup (agent.venv -> .python)
tests/test_cli.py          APPEND — _load_dotenv + _setup tests
commands/self-iterate.md   MODIFY — invoke cli via .self-iterate/.python
skills/self-iterate/SKILL.md  MODIFY — invoke cli via .self-iterate/.python; add setup step
README.md                  MODIFY — note agent.venv + setup picks the interpreter
```

**Signatures:** `_load_dotenv(path=".env") -> None`; `setup` subcommand gains `--eval`; `.self-iterate/.python` holds the interpreter path (one line).

---

## Task 1: `_load_dotenv` helper

**Files:**
- Modify: `scripts/loop_iter/cli.py` (add `_load_dotenv`, call it in `main`)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`:**

```python
import os

def test_load_dotenv_sets_new_and_does_not_override(tmp_path, monkeypatch):
    from loop_iter.cli import _load_dotenv
    env = tmp_path / ".env"
    env.write_text("# comment\n\nNEWKEY=fromfile\nEXISTING=fromfile\nQUOTED=\"q\"\nNOEQ\n")
    monkeypatch.setenv("EXISTING", "explicit")          # pre-set must win
    _load_dotenv(str(env))
    assert os.environ["NEWKEY"] == "fromfile"           # loaded
    assert os.environ["EXISTING"] == "explicit"         # NOT overridden (setdefault)
    assert os.environ["QUOTED"] == "q"                  # quotes stripped
    for k in ("NEWKEY", "QUOTED"):
        monkeypatch.delenv(k, raising=False)


def test_load_dotenv_noop_when_absent(tmp_path):
    from loop_iter.cli import _load_dotenv
    _load_dotenv(str(tmp_path / "nope.env"))            # no error, no effect
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (`ImportError: cannot import name _load_dotenv`).

- [ ] **Step 3: Add to `scripts/loop_iter/cli.py`** (place near the other helpers, before `main`):

```python
def _load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE from .env into os.environ via setdefault (explicit env wins).
    Shell-safe python parse (zsh `source` chokes on some .env lines). No-op if absent."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
```

- [ ] **Step 4: Call it at the top of `main()`** — in `scripts/loop_iter/cli.py`, make the first line of `main`'s body (after `ap = ...` is fine, but before `a.func(a)`):

```python
def main(argv=None):
    _load_dotenv()
    ap = argparse.ArgumentParser(prog="python -m loop_iter.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    # ... (rest unchanged)
```

- [ ] **Step 5:** `.venv/bin/pytest tests/test_cli.py -q` → the 2 new tests pass. Then `.venv/bin/pytest -q` → full suite green (59 passing).

- [ ] **Step 6: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: cli auto-loads .env (shell-safe, setdefault) at startup"
```

---

## Task 2: `setup` resolves the interpreter from `agent.venv` → `.self-iterate/.python`

**Files:**
- Modify: `scripts/loop_iter/cli.py` (`_setup` rewrite + add `--eval` to the `setup` subparser)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`:**

```python
def test_setup_uses_agent_venv_when_set_and_exists(tmp_path):
    import io, contextlib, sys as _sys
    from loop_iter.cli import main
    repo = tmp_path / "repo"; repo.mkdir()
    # fake agent venv with bin/python + bin/pip (so exists() is true + pip no-ops)
    av = repo / ".venv"; (av / "bin").mkdir(parents=True)
    (av / "bin" / "python").write_text("#!/bin/sh\nexec " + _sys.executable + ' "$@"\n')
    (av / "bin" / "python").chmod(0o755)
    (av / "bin" / "pip").write_text("#!/bin/sh\nexit 0\n"); (av / "bin" / "pip").chmod(0o755)
    ev = repo / ".self-iterate" / "g"; ev.mkdir(parents=True)
    (ev / "goal.yaml").write_text(
        "agent:\n  venv: .venv\nthreshold: 0.5\nmax_rounds: 1\nweights: {gates: 1.0}\nregression: block\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["setup", "--eval", str(ev), "--base", str(repo)])
    dotpy = (repo / ".self-iterate" / ".python").read_text()
    assert ".venv/bin/python" in dotpy                       # used the agent venv
    assert ".self-iterate/.venv" not in dotpy                # did NOT bootstrap


def test_setup_bootstraps_when_no_agent_venv(tmp_path, monkeypatch):
    import io, contextlib
    from loop_iter.cli import main
    repo = tmp_path / "repo"; repo.mkdir()
    ev = repo / ".self-iterate" / "g"; ev.mkdir(parents=True)
    (ev / "goal.yaml").write_text(
        "threshold: 0.5\nmax_rounds: 1\nweights: {gates: 1.0}\nregression: block\n")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)   # skip real venv/pip
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["setup", "--eval", str(ev), "--base", str(repo)])
    dotpy = (repo / ".self-iterate" / ".python").read_text()
    assert ".self-iterate/.venv/bin/python" in dotpy         # bootstrapped path
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL (the assertions on `.python` — current `_setup` doesn't write it / doesn't read agent.venv).

- [ ] **Step 3: Replace `_setup` in `scripts/loop_iter/cli.py` with:**

```python
def _setup(args):
    import yaml
    # Resolve the interpreter: agent.venv (if set + exists) else bootstrap .self-iterate/.venv.
    venv_dir = None
    if args.eval:
        goal_path = Path(args.eval, "goal.yaml")
        if goal_path.exists():
            spec = yaml.safe_load(goal_path.read_text()) or {}
            av = (spec.get("agent") or {}).get("venv")
            if av and Path(args.base, av, "bin", "python").exists():
                venv_dir = Path(args.base, av)
    if venv_dir is None:
        venv_dir = Path(args.base, ".self-iterate", ".venv")
        if not venv_dir.exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    py = str(venv_dir / "bin" / "python")
    subprocess.run([str(venv_dir / "bin" / "pip"), "install", "-q", "pyyaml", "httpx"], check=True)
    dotpy = Path(args.base, ".self-iterate", ".python")
    dotpy.parent.mkdir(parents=True, exist_ok=True)
    dotpy.write_text(py)
    print(json.dumps({"python": py, "venv": str(venv_dir), "deps": ["pyyaml", "httpx"]}))
```

- [ ] **Step 4: Add `--eval` to the `setup` subparser in `main()`.** Find the `setup` subparser block and change it to:

```python
    s = sub.add_parser("setup")
    s.add_argument("--eval", default=None, help="eval dir (reads goal.yaml agent.venv)")
    s.add_argument("--base", default=".")
    s.set_defaults(func=_setup)
```

- [ ] **Step 5:** `.venv/bin/pytest tests/test_cli.py -q` → the 2 new tests pass. Then `.venv/bin/pytest -q` → full suite green.

- [ ] **Step 6: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: setup resolves agent.venv -> .self-iterate/.python (else bootstrap)"
```

---

## Task 3: skill + command invoke the cli via `.self-iterate/.python`

**Files:**
- Modify: `commands/self-iterate.md`
- Modify: `skills/self-iterate/SKILL.md`

- [ ] **Step 1: In `skills/self-iterate/SKILL.md`, make every cli invocation use the recorded interpreter.** Add this as the first action under `## One round` (before step 1), and change each `python <plugin-root>/scripts/loop_iter/cli.py …` to `"$PY" <plugin-root>/scripts/loop_iter/cli.py …`. Concretely, insert at the top of `## One round`:

```markdown
**Interpreter.** The cli must run under the agent's own Python (so `python-import` shims find their deps). Use the interpreter recorded by `/self-iterate setup`:
```
PY=$(cat .self-iterate/.python 2>/dev/null || echo python)
```
Use `"$PY"` for every cli call below.
```

  Then replace each occurrence of `python <plugin-root>/scripts/loop_iter/cli.py` in steps 1, 3, 4, 5 with `"$PY" <plugin-root>/scripts/loop_iter/cli.py`. (Leave the command text otherwise unchanged.)

- [ ] **Step 2: In `commands/self-iterate.md`, update the "What it does" step 1** to reflect that `setup` resolves the agent's venv. Replace step 1 with:

```markdown
1. Ensures the Python env is ready: runs `cli.py setup --eval .self-iterate/<goal>` (once). If
   `goal.yaml` has `agent.venv` (e.g. `.venv`), it uses that venv (which has the agent's own deps,
   e.g. `zai_adk`); otherwise it bootstraps `.self-iterate/.venv`. The chosen interpreter is recorded
   in `.self-iterate/.python`, and `.env` is auto-loaded by the cli — so no manual env sourcing.
```

- [ ] **Step 3:** Verify both files still start with `---` frontmatter and the cli paths are intact. No tests affected.

- [ ] **Step 4: Commit:**
```bash
git add skills/self-iterate/SKILL.md commands/self-iterate.md
git commit -m "feat: skill/command invoke cli via .self-iterate/.python (agent venv)"
```

---

## Task 4: README note

**Files:**
- Modify: `README.md` (the `### Install` / adapter-type area)

- [ ] **Step 1: In `README.md`, under the `### Install` subsection, replace the `/self-iterate setup` line** with:

```markdown
/self-iterate setup        # picks the right Python: your agent's `agent.venv` if set (has its own
                           # deps, e.g. zai_adk), else bootstraps .self-iterate/.venv. Records it in
                           # .self-iterate/.python. The cli also auto-loads .env (OPENAI_* etc.) — no
                           # manual sourcing.
```

- [ ] **Step 2: In the `#### Adapter type` table's `python-import` row**, append to "what you provide": ` + agent.venv: .venv` so it reads:

```markdown
| `python-import` | in-process agent (e.g. maas) | `module` + `entry` + `agent.venv: .venv`; a ~5-line `entry(query, variant_dir, **extra)` shim that loads your agent with `skills_dir=variant_dir` |
```

- [ ] **Step 3: Commit:**
```bash
git add README.md
git commit -m "docs: note agent.venv + auto .env in README"
```

---

## Self-Review (completed during authoring)

**1. Spec coverage:** §3.1 `.env` auto-load → Task 1. §3.2 `agent.venv` → `.python` (setup gains `--eval`) → Task 2. §3.3 skill/command invoke via `.python` → Task 3. §4 README note → Task 4. ✓ All spec points covered.

**2. Placeholder scan:** No TBD/TODO. Every code step shows full code; Task 3's "replace each occurrence" is concrete (names the 4 steps + the exact `"$PY"` substitution). No "add error handling" filler.

**3. Type consistency:** `_load_dotenv(path=".env") -> None` consistent in Task 1 (def + tests + main call). `_setup(args)` reads `args.eval` + `args.base` — Task 2 adds `--eval` to the subparser matching the tests' `main(["setup","--eval",...])`. `.self-iterate/.python` path consistent across Task 2 (write) + Task 3 (read via `cat`). `agent.venv` key consistent (goal.yaml `agent.venv` → Task 2 reads `(spec.get("agent") or {}).get("venv")`).
