import json, subprocess, io, contextlib
from pathlib import Path
import pytest


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
    """uv-style: the agent venv (uv-managed) has NO pip at all. setup must still work —
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
    (ev / "rubric.md").write_text("score len")
    # init first
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    # stub run_cases so we don't need a real agent/llm
    captured = {}
    def fake_run_cases(cases, worktree, gates_path, rubric_md, weights, run_case_fn, judge_case_fn=None, llm_call=None):
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
    (ev / "rubric.md").write_text("x")
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
    (ev / "rubric.md").write_text("x")
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


def test_cli_snapshot_refuses_wrong_phase(tmp_path):
    from loop_iter.cli import main
    from loop_iter.adapter import remove_worktree
    from loop_iter.state import RunPaths, init_state, load_state, write_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    st = load_state(rp); st["phase"] = "eval"; write_state(rp, st)   # wrong phase for snapshot
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["apply-variant", "--eval", str(ev), "--base", str(repo)])
    wt = json.loads(buf.getvalue())["worktree"]
    try:
        main(["snapshot", "--eval", str(ev), "--worktree", wt,
              "--dest", str(tmp_path / "snap"), "--base", str(repo), "--run-id", "r1"])
        assert False, "should refuse"
    except SystemExit as e:
        assert "phase guard" in str(e) and "maker" in str(e)
    assert load_state(rp)["phase"] == "eval"   # unchanged
    remove_worktree(wt)


def test_cli_case_run_refuses_wrong_phase(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state, write_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    st = load_state(rp); st["phase"] = "goalcheck"; write_state(rp, st)   # wrong phase for case-run
    import loop_iter.case_runner as cr
    def boom(*a, **k):
        raise AssertionError("run_cases must NOT be called when phase guard refuses")
    monkeypatch.setattr(cr, "run_cases", boom)
    try:
        main(["case-run", "--eval", str(ev), "--worktree", str(repo),
              "--run-id", "r1", "--base", str(repo), "--round", "1"])
        assert False, "should refuse"
    except SystemExit as e:
        assert "phase guard" in str(e) and "eval" in str(e)
    assert load_state(rp)["phase"] == "goalcheck"   # unchanged
    # and scores.json must NOT have been written (guard refused before append_round)
    assert not rp.scores.exists()


def test_cli_report_writes_diff_and_md(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)   # repo has CLAUDE.md = "baseline"
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    append_round(rp, {"round": 1, "composite": 0.9, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    # snapshot an edited variant so the diff has something to show
    snap = rp.variants_dir / "round_1" / "CLAUDE.md"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text("round1-edited")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["report", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    diff = rp.winner_diff.read_text()
    assert "baseline/CLAUDE.md" in diff and "round_1/CLAUDE.md" in diff
    assert "-baseline" in diff and "+round1-edited" in diff
    md = rp.report_md.read_text()
    assert "best round: 1" in md
    assert "composite 0.900" in md

def test_cli_report_skips_missing_snapshot(tmp_path, capsys):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)   # CLAUDE.md = "baseline"
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    append_round(rp, {"round": 1, "composite": 0.9, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    # NO snapshot written for round_1/CLAUDE.md -> must be skipped, not faked as a deletion
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["report", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    diff = rp.winner_diff.read_text()
    assert "-baseline" not in diff          # no fake whole-file deletion
    err = capsys.readouterr().err
    assert "no snapshot for CLAUDE.md" in err   # warning emitted


def test_cli_report_refuses_no_rounds(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    try:
        main(["report", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "should refuse"
    except SystemExit as e:
        assert "no rounds" in str(e)


def test_cli_goal_check_wrong_phase_exits_cleanly(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state, write_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    st = load_state(rp); st["phase"] = "eval"; write_state(rp, st)   # wrong phase for goalcheck
    try:
        main(["goal-check", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
        assert False, "should exit"
    except SystemExit as e:
        assert "phase guard" in str(e)
    except RuntimeError:
        assert False, "cli must convert RuntimeError to SystemExit"


def test_e2e_state_machine_full_flow(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    from loop_iter.adapter import remove_worktree
    repo = _repo(tmp_path)   # CLAUDE.md = "baseline"
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 2\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    rp = RunPaths(base=str(repo), run_id="e2e")
    # stub run_cases: round 1 composite 0.5 (not met), round 2 composite 0.9 (met).
    # NOTE: baseline ALSO calls run_cases (call #1), so round-1 case-run is call #2,
    # round-2 case-run is call #3.
    calls = {"n": 0}
    def fake_run_cases(cases, worktree, gates_path, rubric_md, weights, run_case_fn, judge_case_fn=None, llm_call=None):
        calls["n"] += 1
        comp = 0.5 if calls["n"] <= 2 else 0.9
        return {"cases": [], "composite": comp, "gate_pass_rates": {"x": 1.0}, "judge_means": {}}
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", fake_run_cases)

    def call(*argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(list(argv))
        return buf.getvalue()

    # init + baseline
    call("init", "--goal", "g", "--eval", str(ev), "--run-id", "e2e", "--base", str(repo))
    call("baseline", "--eval", str(ev), "--run-id", "e2e", "--base", str(repo))
    assert load_state(rp)["phase"] == "maker"
    assert load_state(rp)["round"] == 1

    # round 1: maker edits the worktree harness, snapshot, case-run, goal-check (not met -> round 2)
    wt = json.loads(call("apply-variant", "--eval", str(ev), "--base", str(repo)))["worktree"]
    Path(wt, "CLAUDE.md").write_text("round1")
    call("snapshot", "--eval", str(ev), "--worktree", wt,
         "--dest", str(rp.variants_dir / "round_1"), "--base", str(repo), "--run-id", "e2e")
    assert load_state(rp)["phase"] == "eval"
    call("case-run", "--eval", str(ev), "--worktree", wt, "--run-id", "e2e", "--base", str(repo), "--round", "1")
    assert load_state(rp)["phase"] == "goalcheck"
    with pytest.raises(SystemExit) as ei:
        call("goal-check", "--eval", str(ev), "--run-id", "e2e", "--base", str(repo))
    assert ei.value.code == 1   # not met -> exit 1
    st = load_state(rp)
    assert st["phase"] == "maker" and st["round"] == 2   # looped to round 2
    remove_worktree(wt)

    # round 2: met -> done
    wt2 = json.loads(call("apply-variant", "--eval", str(ev), "--base", str(repo)))["worktree"]
    Path(wt2, "CLAUDE.md").write_text("round2-wins")
    call("snapshot", "--eval", str(ev), "--worktree", wt2,
         "--dest", str(rp.variants_dir / "round_2"), "--base", str(repo), "--run-id", "e2e")
    call("case-run", "--eval", str(ev), "--worktree", wt2, "--run-id", "e2e", "--base", str(repo), "--round", "2")
    with pytest.raises(SystemExit) as ei2:
        call("goal-check", "--eval", str(ev), "--run-id", "e2e", "--base", str(repo))
    assert ei2.value.code == 0   # met -> exit 0
    st = load_state(rp)
    assert st["phase"] == "done" and st["met"] is True
    assert st["best"]["round"] == 2 and st["best"]["composite"] == 0.9   # Fix 1
    remove_worktree(wt2)

    # report
    call("report", "--eval", str(ev), "--run-id", "e2e", "--base", str(repo))
    assert rp.winner_diff.exists() and rp.report_md.exists()
    md = rp.report_md.read_text()
    assert "best round: 2" in md and "met: True" in md


def test_cli_baseline_computes_quality_when_quality_md_present(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("rubric: be clear")
    rp = RunPaths(base=str(repo), run_id="r1")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda text, md, llm_call, model="glm-4.7":
        [{"dim": "clarity", "score": 8.0}])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    st = load_state(rp)
    assert st["baseline_quality"] == 9.0   # mean(no_overfit=10.0, clarity=8.0)
    import json
    assert json.loads(rp.baseline_file.read_text())["quality"] == 9.0


def test_cli_baseline_skips_quality_when_no_quality_md(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    # NO quality.md
    rp = RunPaths(base=str(repo), run_id="r1")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    def boom(*a, **k):
        raise AssertionError("judge_quality must not be called without quality.md")
    monkeypatch.setattr(jm, "judge_quality", boom)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    assert load_state(rp)["baseline_quality"] == 10.0   # no_overfit always computed (decoupled from quality.md)


def test_cli_case_run_writes_quality_when_quality_md_present(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state, load_scores
    repo = _repo(tmp_path)                       # CLAUDE.md = "baseline" (the base harness)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("harness: [CLAUDE.md]\nthreshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("rubric: be clear")
    # a DISTINCT worktree dir whose CLAUDE.md differs from the base, so we can prove
    # judge_quality was fed the WORKTREE's harness, not the base's
    wt = tmp_path / "variant_wt"; wt.mkdir()
    (wt / "CLAUDE.md").write_text("VARIANT-HARNESS-CONTENT")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    captured = {}
    def fake_judge_quality(text, md, llm_call, model="glm-4.7"):
        captured["text"] = text
        return [{"dim": "clarity", "score": 7.0}]
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", fake_judge_quality)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(wt),
              "--run-id", "r1", "--base", str(repo), "--round", "1"])
    # core invariant: judge_quality saw the WORKTREE's harness, not the base's
    assert "VARIANT-HARNESS-CONTENT" in captured["text"]
    assert "### CLAUDE.md" in captured["text"]
    import json
    q = json.loads((rp.run_dir / "quality.json").read_text())
    assert q["round"] == 1 and q["quality"] == 8.5   # mean(no_overfit=10.0, clarity=7.0)
    assert load_scores(rp)["rounds"][-1]["quality"] == 8.5
    assert load_state(rp)["phase"] == "goalcheck"


def test_cli_quality_reliable_when_llm_degrades(tmp_path, monkeypatch):
    """Programmatic no_overfit gives a quality signal even when the LLM quality-judge degrades to None
    (the flaky-judge scenario). Baseline with no hardcoding -> quality 10.0 despite LLM None."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = _repo(tmp_path)   # CLAUDE.md = "baseline" (no eval answer hardcoded)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("harness: [CLAUDE.md]\nthreshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"a distinctive long query here","expected":"PARIS"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("rubric: clarity")
    rp = RunPaths(base=str(repo), run_id="r1")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda *a, **k: None)   # LLM degraded
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    assert load_state(rp)["baseline_quality"] == 10.0   # programmatic no_overfit alone, LLM None
    import json
    dims = json.loads(rp.baseline_file.read_text())["quality_dims"]
    assert any(d["dim"] == "no_overfit" and d["score"] == 10.0 for d in dims)


def test_cli_quality_drops_when_harness_hardcodes_answer(tmp_path, monkeypatch):
    """If the harness hardcodes the eval answer, no_overfit drops -> quality lowers (guardrail signal)."""
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, load_state
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("For the capital question, answer Paris.")  # hardcodes "Paris"
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, env=env, check=True)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("harness: [CLAUDE.md]\nthreshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"capital of France","expected":"Paris"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("rubric: clarity")
    rp = RunPaths(base=str(repo), run_id="r1")
    main(["init", "--goal", "g", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.5, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda *a, **k: None)   # LLM degraded
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["baseline", "--eval", str(ev), "--run-id", "r1", "--base", str(repo)])
    assert load_state(rp)["baseline_quality"] == 0.0   # no_overfit=0 (hardcoded), LLM None


def test_cli_smoke_runs_one_case_no_state(tmp_path, monkeypatch):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"},{"id":"c2","query":"yo","expected":"yo"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    import loop_iter.adapter_generic as ag
    monkeypatch.setattr(ag, "build_run_case", lambda eval_dir, cfg, harness:
                        (lambda case, worktree: {"case_id": case["id"], "output": "ok", "trace": {}, "error": None}))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["smoke", "--eval", str(ev), "--base", str(repo)])
    out = json.loads(buf.getvalue())
    assert out["case_id"] == "c1"          # only case[0]
    assert out["error"] is None
    # no run state created
    assert not (repo / ".self-iterate" / "runs").exists()


def test_cli_smoke_exits_1_on_error(tmp_path, monkeypatch):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    import loop_iter.adapter_generic as ag
    monkeypatch.setattr(ag, "build_run_case", lambda eval_dir, cfg, harness:
                        (lambda case, worktree: {"case_id": case["id"], "output": "", "trace": {}, "error": "boom"}))
    try:
        main(["smoke", "--eval", str(ev), "--base", str(repo)])
        assert False, "should exit 1"
    except SystemExit as e:
        assert e.code == 1


def test_cli_smoke_handles_service_adapter(tmp_path, monkeypatch):
    """smoke detects a ServiceAdapter and runs start/run_case/stop (not the per-case callable)."""
    from loop_iter.cli import main
    from loop_iter.adapter_generic import ServiceAdapter
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")

    class FakeSvc(ServiceAdapter):
        def __init__(self):
            super().__init__({}); self.started = 0; self.stopped = 0
        def start(self, worktree): self.started += 1
        def run_case(self, case, worktree):
            return {"case_id": case["id"], "output": "svc-answer", "trace": {}, "error": None}
        def stop(self): self.stopped += 1
    svc = FakeSvc()
    import loop_iter.adapter_generic as ag
    monkeypatch.setattr(ag, "build_run_case", lambda eval_dir, cfg, harness: svc)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["smoke", "--eval", str(ev), "--base", str(repo)])
    out = json.loads(buf.getvalue())
    assert out["output"] == "svc-answer"
    assert svc.started == 1 and svc.stopped == 1


def test_cli_quality_merge_round(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nquality_target: 8.0\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("clarity / maintainability")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    (rp.run_dir / "quality.json").write_text('{"round": 1, "quality": 10.0, "quality_dims": [{"dim": "no_overfit", "score": 10.0}]}')
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 10.0, "gate_pass_rates": {"x": 1.0}, "cases": [], "judge_means": {}})
    judge_path = rp.run_dir / "quality_judge.json"
    judge_path.write_text('{"dims": [{"dim": "clarity", "score": 6.0}, {"dim": "maintainability", "score": 6.0}], "maker_feedback": "trim section 3"}')
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "r1", "--base", str(repo),
              "--round", "1", "--from", str(judge_path)])
    import json
    from loop_iter.state import load_scores
    q = json.loads((rp.run_dir / "quality.json").read_text())
    assert abs(q["quality"] - (10 + 6 + 6) / 3) < 1e-6
    assert q["maker_feedback"] == "trim section 3"
    assert any(d["dim"] == "no_overfit" and d["score"] == 10.0 for d in q["quality_dims"])
    assert load_scores(rp)["rounds"][-1]["quality"] == q["quality"]


def test_cli_quality_merge_baseline(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_state, write_state
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nquality_target: 8.0\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    rp.baseline_file.write_text('{"composite": 0.5, "quality": 10.0, "quality_dims": [{"dim":"no_overfit","score":10.0}]}')
    st = load_state(rp); st["baseline_quality"] = 10.0; write_state(rp, st)
    judge_path = rp.run_dir / "quality_judge_baseline.json"
    judge_path.write_text('{"dims": [{"dim": "clarity", "score": 9.0}], "maker_feedback": ""}')
    import io, contextlib, json
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "r1", "--base", str(repo),
              "--baseline", "--from", str(judge_path)])
    b = json.loads(rp.baseline_file.read_text())
    assert abs(b["quality"] - (10 + 9) / 2) < 1e-6
    assert load_state(rp)["baseline_quality"] == b["quality"]


def test_cli_quality_merge_overrides_subagent_no_overfit(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    (rp.run_dir / "quality.json").write_text('{"round": 1, "quality": 10.0, "quality_dims": [{"dim": "no_overfit", "score": 10.0}]}')
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 10.0, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    judge_path = rp.run_dir / "quality_judge.json"
    judge_path.write_text('{"dims": [{"dim": "no_overfit", "score": 2.0}, {"dim": "clarity", "score": 8.0}], "maker_feedback": ""}')
    import io, contextlib, json
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["quality-merge", "--eval", str(ev), "--run-id", "r1", "--base", str(repo),
              "--round", "1", "--from", str(judge_path)])
    q = json.loads((rp.run_dir / "quality.json").read_text())
    no_overfit = [d for d in q["quality_dims"] if d["dim"] == "no_overfit"][0]
    assert no_overfit["score"] == 10.0
    assert len(q["quality_dims"]) == 2


def test_cli_case_run_skips_llm_quality_when_quality_target_set(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_scores
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nquality_target: 8.0\nharness: [CLAUDE.md]\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    def boom(*a, **k):
        raise AssertionError("judge_quality must NOT be called when quality_target set")
    monkeypatch.setattr(jm, "judge_quality", boom)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo), "--run-id", "r1", "--base", str(repo), "--round", "1"])
    assert load_scores(rp)["rounds"][-1]["quality"] == 10.0
    dims = load_scores(rp)["rounds"][-1]["quality_dims"]
    assert [d["dim"] for d in dims] == ["no_overfit"]


def test_cli_case_run_keeps_llm_quality_when_no_quality_target(tmp_path, monkeypatch):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, load_scores
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\nharness: [CLAUDE.md]\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"hi","expected":"hi"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    import loop_iter.state as stmod
    st = stmod.load_state(rp); st["phase"] = "eval"; st["round"] = 1; stmod.write_state(rp, st)
    import loop_iter.case_runner as cr
    monkeypatch.setattr(cr, "run_cases", lambda *a, **k:
        {"cases": [], "composite": 0.9, "gate_pass_rates": {}, "judge_means": {}})
    import loop_iter.judge as jm
    monkeypatch.setattr(jm, "judge_quality", lambda *a, **k: [{"dim": "clarity", "score": 7.0}])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["case-run", "--eval", str(ev), "--worktree", str(repo), "--run-id", "r1", "--base", str(repo), "--round", "1"])
    dims = load_scores(rp)["rounds"][-1]["quality_dims"]
    assert {"dim": "clarity", "score": 7.0} in dims
    assert any(d["dim"] == "no_overfit" for d in dims)


def test_cli_quality_merge_round_not_found_errors(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    (rp.run_dir / "quality.json").write_text('{"round": 1, "quality": 10.0, "quality_dims": [{"dim":"no_overfit","score":10.0}]}')
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 10.0, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    jp = rp.run_dir / "qj.json"; jp.write_text('{"dims": [{"dim":"clarity","score":8.0}], "maker_feedback": ""}')
    try:
        main(["quality-merge", "--eval", str(ev), "--run-id", "r1", "--base", str(repo), "--round", "99", "--from", str(jp)])
        assert False, "should error on missing round"
    except SystemExit as e:
        assert "round 99" in str(e)


def test_cli_quality_merge_malformed_json_errors(tmp_path):
    from loop_iter.cli import main
    from loop_iter.state import RunPaths, init_state, append_round
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    (ev / "quality.md").write_text("clarity")
    rp = RunPaths(base=str(repo), run_id="r1"); init_state(rp, "g", 3)
    (rp.run_dir / "quality.json").write_text('{"round": 1, "quality": 10.0, "quality_dims": [{"dim":"no_overfit","score":10.0}]}')
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 10.0, "gate_pass_rates": {}, "cases": [], "judge_means": {}})
    jp = rp.run_dir / "qj.json"; jp.write_text("not json at all")
    try:
        main(["quality-merge", "--eval", str(ev), "--run-id", "r1", "--base", str(repo), "--round", "1", "--from", str(jp)])
        assert False, "should error on malformed JSON"
    except SystemExit as e:
        assert "invalid quality-judge JSON" in str(e)


def test_cli_dashboard_starts_and_serves(tmp_path, monkeypatch):
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    from loop_iter.state import RunPaths, init_state
    rp = RunPaths(base=str(repo), run_id="d1"); init_state(rp, "g", 3)
    import loop_iter.dashboard as dash
    def fake_serve(eval_dir, run_id, base, port=0):
        print(json.dumps({"url": "http://127.0.0.1:9999", "port": 9999}))
    monkeypatch.setattr(dash, "serve", fake_serve)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["dashboard", "--eval", str(ev), "--run-id", "d1", "--base", str(repo)])
    out = json.loads(buf.getvalue())
    assert "url" in out and "port" in out
