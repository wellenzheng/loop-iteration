import json, subprocess, io, contextlib
from pathlib import Path


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("baseline")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, env=env, check=True)
    return repo


def test_cli_goal_check_no_rounds_exits_1(tmp_path):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    try:
        main(["goal-check", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "should have exited 1"
    except SystemExit as e:
        assert e.code == 1


def test_cli_apply_variant_prints_worktree_and_harness(tmp_path):
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    data = json.loads(buf.getvalue())
    assert "worktree" in data and Path(data["worktree"]).exists()
    assert data["harness"] == ["CLAUDE.md"]
    remove_worktree(data["worktree"])
    assert (repo / "CLAUDE.md").read_text() == "baseline"


def test_cli_snapshot_copies_harness_from_worktree(tmp_path):
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    # stage a worktree, edit the harness there, then snapshot it
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    wt = json.loads(buf.getvalue())["worktree"]
    Path(wt, "CLAUDE.md").write_text("round1-edited")
    dest = tmp_path / "snap"
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        main(["snapshot", "--eval", str(ev), "--worktree", wt, "--dest", str(dest), "--base", str(repo)])
    out = json.loads(buf2.getvalue())
    assert out["files"] == ["CLAUDE.md"]
    assert (dest / "CLAUDE.md").read_text() == "round1-edited"
    remove_worktree(wt)


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


def test_setup_uses_agent_venv_when_set_and_exists(tmp_path):
    import io, contextlib, sys as _sys
    from loop_iter.cli import main
    repo = tmp_path / "repo"; repo.mkdir()
    # fake agent venv with bin/python + bin/pip (exists() true, pip no-ops)
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


def test_setup_resolves_agent_venv_without_pyyaml(tmp_path, monkeypatch):
    import io, contextlib, sys as _sys, sys
    from loop_iter.cli import main
    repo = tmp_path / "repo"; repo.mkdir()
    av = repo / ".venv"; (av / "bin").mkdir(parents=True)
    (av / "bin" / "python").write_text("#!/bin/sh\nexec " + _sys.executable + ' "$@"\n')
    (av / "bin" / "python").chmod(0o755)
    (av / "bin" / "pip").write_text("#!/bin/sh\nexit 0\n"); (av / "bin" / "pip").chmod(0o755)
    ev = repo / ".self-iterate" / "g"; ev.mkdir(parents=True)
    (ev / "goal.yaml").write_text(
        "agent:\n  type: python-import\n  venv: .venv\nthreshold: 0.5\nmax_rounds: 1\nweights: {gates: 1.0}\nregression: block\n")
    monkeypatch.setitem(sys.modules, "yaml", None)   # `import yaml` -> ImportError -> regex fallback
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["setup", "--eval", str(ev), "--base", str(repo)])
    dotpy = (repo / ".self-iterate" / ".python").read_text()
    assert ".venv/bin/python" in dotpy                       # resolved agent.venv without pyyaml
    assert ".self-iterate/.venv" not in dotpy                # did NOT bootstrap


def test_setup_agent_venv_without_pip(tmp_path, monkeypatch):
    """maas-style: the agent venv (uv-managed) has NO pip at all. setup must still work —
    it must NOT try to shell out to pip (the deps are the agent owner's responsibility)."""
    import io, contextlib, sys as _sys
    from loop_iter.cli import main
    repo = tmp_path / "repo"; repo.mkdir()
    av = repo / ".venv"; (av / "bin").mkdir(parents=True)
    # a python but NO bin/pip and NO pip module (uv venv)
    (av / "bin" / "python").write_text("#!/bin/sh\nexec " + _sys.executable + ' "$@"\n')
    (av / "bin" / "python").chmod(0o755)
    ev = repo / ".self-iterate" / "g"; ev.mkdir(parents=True)
    (ev / "goal.yaml").write_text(
        "agent:\n  venv: .venv\nthreshold: 0.5\nmax_rounds: 1\nweights: {gates: 1.0}\nregression: block\n")

    def boom(*a, **k):
        raise AssertionError("setup must not call subprocess for an agent venv (no pip needed)")
    monkeypatch.setattr("subprocess.run", boom)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["setup", "--eval", str(ev), "--base", str(repo)])
    dotpy = (repo / ".self-iterate" / ".python").read_text()
    assert ".venv/bin/python" in dotpy                       # used the agent venv
    assert ".self-iterate/.venv" not in dotpy                # did NOT bootstrap


def test_cli_init_writes_state_baseline(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 4\nweights: {gates: 1.0}\nregression: block\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    st = load_state(RunPaths(base=str(repo), run_id="r1"))
    assert st["phase"] == "baseline"
    assert st["max_rounds"] == 4
    assert json.loads(buf.getvalue())["phase"] == "baseline"


def test_cli_baseline_runs_cases_and_advances_to_maker(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("score len")
    # init first
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    # stub run_cases so we don't need a real agent/llm
    captured = {}
    def fake_run_cases(cases, worktree, gates_path, judge_md, weights, run_case_fn, judge_case_fn=None, llm_call=None):
        captured["called"] = True
        return {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}}
    monkeypatch.setattr("loop_iter.cli.run_cases", fake_run_cases, raising=False)
    # cli imports run_cases lazily inside _baseline via `from loop_iter.case_runner import run_cases`;
    # patch the source module so the lazy import picks up the stub:
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", fake_run_cases)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    assert captured["called"]
    st = load_state(RunPaths(base=str(repo), run_id="r1"))
    assert st["phase"] == "maker"
    assert st["round"] == 1
    assert st["baseline_composite"] == 0.5
    rp = RunPaths(base=str(repo), run_id="r1")
    assert json.loads(rp.baseline_file.read_text())["composite"] == 0.5


def test_cli_baseline_refuses_wrong_phase(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text("[]")
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    rp = RunPaths(base=str(repo), run_id="r1")
    init_state(rp, "g", 3)
    advance_to = rp  # force phase out of baseline
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "maker"; stmod.write_state(rp, st)
    try:
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "should refuse"
    except SystemExit as e:
        assert "phase guard" in str(e)


def test_cli_init_refuses_to_clobber_existing_run(tmp_path):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 4\nweights: {gates: 1.0}\nregression: block\n")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    # advance phase so we can detect clobbering (state would be lost)
    from loop_iter.state import RunPaths, load_state, write_state
    rp = RunPaths(base=str(repo), run_id="r1")
    st = load_state(rp); st["phase"] = "maker"; write_state(rp, st)
    try:
        main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "re-init should refuse"
    except SystemExit as e:
        assert "already initialized" in str(e)
    # state must be untouched (still maker, not reset to baseline)
    assert load_state(rp)["phase"] == "maker"


def test_cli_snapshot_advances_maker_to_eval_inside_run(tmp_path):
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    from loop_iter.state import RunPaths, init_state, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = load_state(rp); st["phase"] = "maker"; st["round"] = 1; stmod.write_state(rp, st)
    # stage a worktree + edit harness
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    wt = json.loads(buf.getvalue())["worktree"]
    Path(wt, "CLAUDE.md").write_text("edited")
    dest = str(rp.variants_dir / "round_1")
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        main(["snapshot", "--eval", str(ev), "--worktree", wt, "--dest", dest,
              "--base", str(repo), "--run-id", "r1"])
    assert load_state(rp)["phase"] == "eval"
    remove_worktree(wt)


def test_cli_snapshot_legacy_without_run_id_unchanged(tmp_path):
    # no state.json, no --run-id -> behaves as before, no phase advance
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    wt = json.loads(buf.getvalue())["worktree"]
    Path(wt, "CLAUDE.md").write_text("edited")
    dest = tmp_path / "snap"
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        main(["snapshot", "--eval", str(ev), "--worktree", wt, "--dest", str(dest), "--base", str(repo)])
    assert (dest / "CLAUDE.md").read_text() == "edited"   # snapshot still worked
    remove_worktree(wt)


def test_cli_case_run_advances_eval_to_goalcheck_inside_run(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "judge.md").write_text("x")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo),
              "--run-id", "r1", "--base", str(repo), "--round", "1"])
    assert load_state(rp)["phase"] == "goalcheck"
