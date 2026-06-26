# real-time dashboard — Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** A real-time interactive HTML dashboard that shows the self-iterate loop's progress live (5 panels: live progress / results overview / quality ratings / case comparison / diff), served by a stdlib HTTP server that reads the run dir. Read-only view over the state machine's writes — never drives the loop.

**Architecture:** `dashboard.py` serves a stdlib `http.server`: `/` → `index.html` (vanilla JS SPA), `/api/state` → `build_state_payload(run_dir)` merging state.json + baseline.json + scores.json + quality.json + winner.diff into one JSON. The page polls `/api/state` every 1.5s and re-renders. New cli `dashboard --eval --run-id` starts the server + prints the URL. The self-iterate skill launches it in the background on `start`. Static `report.md` + `winner.diff` still generated at `done` (offline archive).

**Tech Stack:** Python 3.11+ stdlib `http.server`/`json`/`pathlib`; vanilla JS + CSS + inline SVG (no build step, no external deps).

**Spec:** [setup+loop spec](2026-06-24-self-iterate-setup-and-loop-design.md) §3.7 (D8).

---

## File Structure

```
scripts/loop_iter/dashboard.py             CREATE — build_state_payload + serve (HTTP server)
scripts/loop_iter/dashboard_assets/        CREATE — index.html (SPA)
scripts/loop_iter/cli.py                   MODIFY — dashboard subcommand
skills/self-iterate/SKILL.md               MODIFY — launch dashboard on start
tests/test_dashboard.py                    CREATE — build_state_payload tests
tests/test_dashboard_integration.py        CREATE — start server, hit /api/state, verify
```

**Signatures:**
- `dashboard.build_state_payload(run_dir: Path) -> dict` — merges all run artifacts into one payload.
- `dashboard.serve(eval_dir: str, run_id: str, base: str, port: int = 0)` — starts the HTTP server (port 0 = auto).
- `cli.dashboard --eval <goal> --run-id <id> [--base .] [--port 0]` — starts the server, prints URL.

---

## Task 1: `dashboard.py` — `build_state_payload` + HTTP server

**Files:** Create `scripts/loop_iter/dashboard.py`, Create `tests/test_dashboard.py`

- [ ] **Step 1: Create `tests/test_dashboard.py`:**

```python
import json
from pathlib import Path
from loop_iter.dashboard import build_state_payload


def test_payload_from_empty_run_dir(tmp_path):
    p = build_state_payload(tmp_path)
    assert p["phase"] is None
    assert p["rounds"] == []


def test_payload_merges_state_baseline_scores(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "phase": "done", "round": 2, "max_rounds": 3, "met": True,
        "baseline_composite": 0.75, "baseline_quality": 5.0,
        "best": {"round": 2, "composite": 1.0, "worktree": None},
        "goal": "one-word", "run_id": "r1"}))
    (tmp_path / "baseline.json").write_text(json.dumps({
        "composite": 0.75, "gate_pass_rates": {"is_one_word": 0.5}, "quality": 5.0,
        "quality_dims": [{"dim": "no_overfit", "score": 10.0}]}))
    (tmp_path / "scores.json").write_text(json.dumps({
        "rounds": [
            {"round": 1, "composite": 1.0, "quality": 7.29,
             "gate_pass_rates": {"is_one_word": 1.0}, "cases": [{"case_id": "c1", "output": "Paris"}]},
            {"round": 2, "composite": 1.0, "quality": 9.0,
             "gate_pass_rates": {"is_one_word": 1.0}, "cases": [{"case_id": "c1", "output": "Paris"}]}
        ], "best_round": 2}))
    p = build_state_payload(tmp_path)
    assert p["phase"] == "done"
    assert p["met"] is True
    assert p["best"]["round"] == 2
    assert p["baseline"]["composite"] == 0.75
    assert len(p["rounds"]) == 2
    assert p["rounds"][0]["quality"] == 7.29
    assert p["rounds"][1]["quality"] == 9.0
    assert p["best_round"] == 2


def test_payload_includes_winner_diff_and_quality(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"phase": "done", "met": True}))
    (tmp_path / "winner.diff").write_text("--- baseline\n+++ round_2\n-old\n+new")
    (tmp_path / "quality.json").write_text(json.dumps(
        {"round": 2, "quality": 9.0, "quality_dims": [{"dim": "clarity", "score": 9.0}],
         "maker_feedback": "clean"}))
    p = build_state_payload(tmp_path)
    assert "winner_diff" in p
    assert "+new" in p["winner_diff"]
    assert p["latest_quality"]["quality"] == 9.0
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_dashboard.py -q` → expect FAIL.

- [ ] **Step 3: Create `scripts/loop_iter/dashboard.py`:**

```python
"""Real-time dashboard: a stdlib HTTP server that serves a SPA + /api/state (merging the run dir).
Read-only view over the state machine's writes — never drives the loop."""
from __future__ import annotations
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ASSETS_DIR = Path(__file__).parent / "dashboard_assets"


def build_state_payload(run_dir: Path) -> dict:
    """Merge all run artifacts into one JSON payload for the dashboard."""
    payload: dict = {"rounds": [], "phase": None, "met": None, "best_round": None,
                     "baseline": None, "latest_quality": None, "winner_diff": None}

    state_path = run_dir / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        for k in ("phase", "round", "max_rounds", "met", "baseline_composite",
                  "baseline_quality", "best", "goal", "run_id", "started_at", "updated_at"):
            if k in state:
                payload[k] = state[k]

    baseline_path = run_dir / "baseline.json"
    if baseline_path.exists():
        b = json.loads(baseline_path.read_text())
        payload["baseline"] = {
            "composite": b.get("composite"), "gate_pass_rates": b.get("gate_pass_rates"),
            "quality": b.get("quality"), "quality_dims": b.get("quality_dims")}

    scores_path = run_dir / "scores.json"
    if scores_path.exists():
        data = json.loads(scores_path.read_text())
        payload["rounds"] = data.get("rounds", [])
        payload["best_round"] = data.get("best_round")

    quality_path = run_dir / "quality.json"
    if quality_path.exists():
        payload["latest_quality"] = json.loads(quality_path.read_text())

    diff_path = run_dir / "winner.diff"
    if diff_path.exists():
        payload["winner_diff"] = diff_path.read_text()

    return payload


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            payload = build_state_payload(self.server.run_dir)  # type: ignore
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/", "/index.html"):
            html_path = ASSETS_DIR / "index.html"
            if html_path.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(html_path.read_bytes())
            else:
                self.send_error(404, "index.html not found")
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass  # quiet


def serve(eval_dir: str, run_id: str, base: str = ".", port: int = 0):
    """Start the dashboard HTTP server. port=0 = auto-pick. Blocks (run in background)."""
    from loop_iter.state import RunPaths
    rp = RunPaths(base=base, run_id=run_id)
    run_dir = rp.run_dir
    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.run_dir = run_dir  # type: ignore
    actual_port = server.server_address[1]
    print(json.dumps({"url": f"http://127.0.0.1:{actual_port}", "port": actual_port,
                      "run_dir": str(run_dir)}))
    server.serve_forever()
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_dashboard.py -q` → pass. `.venv/bin/pytest -q` → green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/dashboard.py tests/test_dashboard.py
git commit -m "feat: dashboard.py — build_state_payload + stdlib HTTP server"
```

---

## Task 2: `cli dashboard` subcommand

**Files:** Modify `scripts/loop_iter/cli.py`, Test `tests/test_cli.py` (append)

- [ ] **Step 1: Append test to `tests/test_cli.py`:**

```python
def test_cli_dashboard_starts_and_serves_api(tmp_path, monkeypatch):
    """dashboard subcommand starts the server and /api/state responds. We stub serve_forever
    to just serve one request then exit."""
    from loop_iter.cli import main
    repo = _repo(tmp_path)
    ev = tmp_path / "eval"; ev.mkdir()
    (ev / "goal.yaml").write_text("threshold: 0.8\nmax_rounds: 3\nweights: {gates: 1.0}\nregression: block\n")
    (ev / "cases.json").write_text('[{"id":"c1","query":"q"}]')
    (ev / "gates.py").write_text("GATES = {}")
    (ev / "rubric.md").write_text("x")
    # create a run dir with state
    from loop_iter.state import RunPaths, init_state
    rp = RunPaths(base=str(repo), run_id="d1"); init_state(rp, "g", 3)
    # stub HTTPServer.serve_forever to do nothing (just return) so the cli returns
    import loop_iter.dashboard as dash
    original_serve = dash.serve
    def fake_serve(eval_dir, run_id, base, port=0):
        print(json.dumps({"url": "http://127.0.0.1:9999", "port": 9999}))
    monkeypatch.setattr(dash, "serve", fake_serve)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["dashboard", "--eval", str(ev), "--run-id", "d1", "--base", str(repo)])
    out = json.loads(buf.getvalue())
    assert "url" in out and "port" in out
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q` → expect FAIL.

- [ ] **Step 3: Add `_dashboard` + subparser to `scripts/loop_iter/cli.py`:**

```python
def _dashboard(args):
    from loop_iter.dashboard import serve
    serve(eval_dir=args.eval, run_id=args.run_id, base=args.base, port=args.port)
```

Subparser (after `quality-merge`):
```python
    s = sub.add_parser("dashboard")
    s.add_argument("--eval", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--base", default=".")
    s.add_argument("--port", type=int, default=0)
    s.set_defaults(func=_dashboard)
```

- [ ] **Step 4:** `.venv/bin/pytest tests/test_cli.py -q` → pass. `.venv/bin/pytest -q` → green.

- [ ] **Step 5: Commit:**
```bash
git add scripts/loop_iter/cli.py tests/test_cli.py
git commit -m "feat: cli dashboard subcommand"
```

---

## Task 3: SPA — `dashboard_assets/index.html`

**Files:** Create `scripts/loop_iter/dashboard_assets/index.html`

- [ ] **Step 1: Create `scripts/loop_iter/dashboard_assets/index.html`** — a single-page app with 5 panels. The full HTML/CSS/JS:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>self-iterate dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; padding: 16px; }
  h1 { font-size: 1.4rem; margin-bottom: 12px; }
  h2 { font-size: 1.1rem; margin-bottom: 8px; color: #58a6ff; }
  .grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
  .panel { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 14px; }
  .full { grid-column: 1 / -1; }
  .stat { display: inline-block; margin-right: 16px; }
  .stat b { color: #58a6ff; }
  .phase-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem; }
  .phase-done { background: #1a7f37; color: #fff; }
  .phase-running { background: #1f6feb; color: #fff; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #30363d; }
  th { color: #8b949e; }
  .diff-add { color: #3fb950; }
  .diff-del { color: #f85149; }
  .diff-meta { color: #8b949e; }
  pre { font-size: 0.8rem; overflow-x: auto; max-height: 400px; }
  select { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 4px; border-radius: 4px; }
  .case-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .case-box { background: #0d1117; border: 1px solid #30363d; padding: 8px; border-radius: 4px; font-size: 0.85rem; min-height: 60px; }
  .quality-bar { height: 12px; border-radius: 3px; background: #1f6feb; display: inline-block; vertical-align: middle; }
  .quality-target { color: #f0883e; font-weight: bold; }
</style>
</head>
<body>
<h1>self-iterate dashboard</h1>
<div id="app">Loading…</div>
<script>
const POLL_MS = 1500;
let lastData = null;

async function fetchState() {
  try {
    const r = await fetch('/api/state');
    return await r.json();
  } catch (e) { return null; }
}

function render(data) {
  if (!data) { document.getElementById('app').innerHTML = '<p>Waiting for run data…</p>'; return; }
  lastData = data;
  const phase = data.phase || '—';
  const met = data.met;
  const round = data.round || 0;
  const maxRounds = data.max_rounds || '—';
  const baselineComp = data.baseline_composite ?? '—';
  const baselineQual = data.baseline_quality ?? '—';
  const best = data.best || {};
  const rounds = data.rounds || [];
  const baseline = data.baseline || {};
  const latestQ = data.latest_quality || {};
  const diff = data.winner_diff || '';

  // Panel 1: Live progress
  const phaseClass = phase === 'done' ? 'phase-done' : 'phase-running';
  let progress = `
    <div class="panel full">
      <h2>Live Progress</h2>
      <span class="stat">Phase: <span class="phase-badge ${phaseClass}">${phase}</span></span>
      <span class="stat">Round: <b>${round}</b> / ${maxRounds}</span>
      <span class="stat">Met: <b>${met === true ? '✅' : met === false ? '❌' : '—'}</b></span>
      <span class="stat">Baseline composite: <b>${baselineComp}</b></span>
      <span class="stat">Baseline quality: <b>${baselineQual}</b></span>
      ${best.round ? `<span class="stat">Best: <b>round ${best.round}</b> (composite ${best.composite})</span>` : ''}
    </div>`;

  // Panel 2: Results overview (trajectory)
  let overview = `<div class="panel"><h2>Results Overview</h2>`;
  if (rounds.length) {
    overview += `<table><tr><th>Round</th><th>Composite</th><th>Quality</th><th>Gates</th></tr>`;
    rounds.forEach(r => {
      const gates = Object.entries(r.gate_pass_rates || {}).map(([k,v]) => `${k}: ${(v*100).toFixed(0)}%`).join(', ');
      overview += `<tr><td>${r.round}</td><td>${(r.composite*100).toFixed(0)}%</td><td>${r.quality?.toFixed(1) ?? '—'}</td><td>${gates}</td></tr>`;
    });
    overview += `</table>`;
    // simple SVG trajectory
    if (rounds.length >= 1) {
      overview += svgTrajectory(rounds, data);
    }
  } else {
    overview += `<p>No rounds yet.</p>`;
  }
  overview += `</div>`;

  // Panel 3: Quality ratings
  let quality = `<div class="panel"><h2>Quality Ratings</h2>`;
  if (latestQ.quality_dims?.length) {
    quality += `<table><tr><th>Dim</th><th>Score</th><th>Bar</th></tr>`;
    latestQ.quality_dims.forEach(d => {
      const bar = `<span class="quality-bar" style="width:${d.score*10}px"></span>`;
      quality += `<tr><td>${d.dim}</td><td>${d.score.toFixed(1)}</td><td>${bar}</td></tr>`;
    });
    quality += `</table>`;
    quality += `<p>Overall: <b>${latestQ.quality?.toFixed(2)}</b>`;
    if (data.quality_target) quality += ` <span class="quality-target">(target: ${data.quality_target})</span>`;
    quality += `</p>`;
    if (latestQ.maker_feedback) quality += `<p style="margin-top:8px;font-size:0.85rem;color:#8b949e">Feedback: ${latestQ.maker_feedback}</p>`;
  } else {
    quality += `<p>No quality data yet.</p>`;
  }
  quality += `</div>`;

  // Panel 4: Case comparison
  let casePanel = `<div class="panel"><h2>Case Comparison</h2>`;
  if (rounds.length && rounds[0].cases?.length) {
    const caseIds = rounds[0].cases.map(c => c.case_id);
    casePanel += `<select id="caseSelect">${caseIds.map(id => `<option value="${id}">${id}</option>`).join('')}</select>`;
    casePanel += `<select id="roundSelect" style="margin-left:8px">`;
    rounds.forEach(r => { casePanel += `<option value="${r.round}">Round ${r.round}</option>`; });
    casePanel += `</select>`;
    casePanel += `<div class="case-compare" style="margin-top:8px"><div><b>Baseline</b><div class="case-box" id="baselineOutput">—</div></div><div><b>Selected</b><div class="case-box" id="selectedOutput">—</div></div></div>`;
    casePanel += `<script>function updateCase(){const cid=document.getElementById('caseSelect').value;const rid=parseInt(document.getElementById('roundSelect').value);const rounds=lastData.rounds||[];const r=rounds.find(r=>r.round===rid);const c=r?.cases?.find(c=>c.case_id===cid);document.getElementById('selectedOutput').textContent=c?.output||'(no data)';const bl=lastData.baseline?.cases?.find(c=>c.case_id===cid);document.getElementById('baselineOutput').textContent=bl?.output||'(no baseline case data)';}document.getElementById('caseSelect').addEventListener('change',updateCase);document.getElementById('roundSelect').addEventListener('change',updateCase);updateCase();<\/script>`;
  } else {
    casePanel += `<p>No case data yet.</p>`;
  }
  casePanel += `</div>`;

  // Panel 5: Diff
  let diffPanel = `<div class="panel full"><h2>Diff (winner vs baseline)</h2>`;
  if (diff) {
    const lines = diff.split('\n').map(l => {
      if (l.startsWith('+++') || l.startsWith('---')) return `<span class="diff-meta">${l}</span>`;
      if (l.startsWith('+')) return `<span class="diff-add">${l}</span>`;
      if (l.startsWith('-')) return `<span class="diff-del">${l}</span>`;
      return l;
    }).join('\n');
    diffPanel += `<pre>${lines}</pre>`;
  } else {
    diffPanel += `<p>No diff yet (run not complete).</p>`;
  }
  diffPanel += `</div>`;

  document.getElementById('app').innerHTML = progress + `<div class="grid">` + overview + quality + casePanel + `</div>` + diffPanel;
}

function svgTrajectory(rounds, data) {
  const w = 280, h = 80, pad = 20;
  const maxRound = Math.max(rounds.length, 1);
  const compPoints = rounds.map((r, i) => `${pad + i*(w-2*pad)/Math.max(maxRound-1,1)},${h-pad - (r.composite||0)*(h-2*pad)}`).join(' ');
  const qualPoints = rounds.map((r, i) => {
    const q = r.quality ? (r.quality/10) : 0;
    return `${pad + i*(w-2*pad)/Math.max(maxRound-1,1)},${h-pad - q*(h-2*pad)}`;
  }).join(' ');
  return `<svg width="${w}" height="${h}" style="margin-top:8px">
    <text x="${pad}" y="12" font-size="9" fill="#3fb950">composite</text>
    <text x="${w-pad-30}" y="12" font-size="9" fill="#f0883e">quality</text>
    <polyline points="${compPoints}" fill="none" stroke="#3fb950" stroke-width="1.5"/>
    <polyline points="${qualPoints}" fill="none" stroke="#f0883e" stroke-width="1.5"/>
  </svg>`;
}

async function poll() {
  const data = await fetchState();
  render(data);
}
poll();
setInterval(poll, POLL_MS);
</script>
</body>
</html>
```

- [ ] **Step 2:** No tests (visual SPA). Run `.venv/bin/pytest -q` (confirm green).

- [ ] **Step 3: Commit:**
```bash
git add scripts/loop_iter/dashboard_assets/index.html
git commit -m "feat: dashboard SPA (5 panels: progress/overview/quality/cases/diff)"
```

---

## Task 4: self-iterate skill — launch dashboard on start

**Files:** Modify `skills/self-iterate/SKILL.md`

- [ ] **Step 1:** In the self-iterate SKILL.md, in the Loop section (before step 1 Init), add:

```markdown
**Dashboard (optional).** To watch the loop live, start the dashboard in the background before
init:
```
"$PY" <plugin>/scripts/loop_iter/cli.py dashboard --eval .self-iterate/<goal> --run-id <run_id> --base . &
```
It prints a URL (e.g. `http://127.0.0.1:<port>`). Open it in a browser — the page polls every 1.5s
and shows live progress, per-round scores, quality dims, case comparison, and the winner diff. The
dashboard is read-only; it never drives the loop.
```

- [ ] **Step 2:** No tests (docs). `.venv/bin/pytest -q` green.

- [ ] **Step 3: Commit:**
```bash
git add skills/self-iterate/SKILL.md
git commit -m "docs: self-iterate skill launches dashboard on start"
```

---

## Task 5: integration test

**Files:** Create `tests/test_dashboard_integration.py`

- [ ] **Step 1: Create `tests/test_dashboard_integration.py`:**

```python
"""Integration: start the dashboard server, hit /api/state + /, verify payload + HTML served."""
import json, threading, time, urllib.request
from pathlib import Path
from loop_iter.dashboard import serve
from loop_iter.state import RunPaths, init_state, append_round


def test_dashboard_serves_api_and_html(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    rp = RunPaths(base=str(repo), run_id="di"); init_state(rp, "g", 3)
    append_round(rp, {"round": 1, "composite": 0.9, "quality": 8.0,
                      "gate_pass_rates": {"x": 1.0}, "cases": [{"case_id": "c1", "output": "hi"}],
                      "judge_means": {}})

    # start server in a thread
    server_started = threading.Event()
    result = {}

    def run_server():
        import http.server
        from loop_iter.dashboard import _Handler, ASSETS_DIR
        from http.server import HTTPServer
        srv = HTTPServer(("127.0.0.1", 0), _Handler)
        srv.run_dir = rp.run_dir
        result["port"] = srv.server_address[1]
        server_started.set()
        srv.handle_request()  # serve one request then exit
        srv.handle_request()  # serve second request (index.html)

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    server_started.wait(timeout=5)
    port = result["port"]

    # hit /api/state
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5)
    payload = json.loads(resp.read())
    assert payload["phase"] == "baseline"  # init_state sets phase=baseline
    assert len(payload["rounds"]) == 1
    assert payload["rounds"][0]["composite"] == 0.9

    # hit / (index.html)
    resp2 = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
    html = resp2.read().decode()
    assert "<html" in html.lower()
    assert "self-iterate dashboard" in html.lower()
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_dashboard_integration.py -q` → pass. `.venv/bin/pytest -q` → green.

- [ ] **Step 3: Commit:**
```bash
git add tests/test_dashboard_integration.py
git commit -m "test: dashboard integration (server + /api/state + index.html)"
```

---

## Self-Review

**1. Spec coverage (§3.7/D8):**
- stdlib HTTP server + SPA → Task 1 (server) + Task 3 (SPA). ✓
- /api/state merging run artifacts → Task 1 (build_state_payload). ✓
- 5 panels (progress/overview/quality/cases/diff) → Task 3 (SPA). ✓
- cli dashboard subcommand → Task 2. ✓
- skill launches on start → Task 4. ✓
- read-only (never drives loop) → dashboard only reads files. ✓
- static archive (report.md + winner.diff) → already implemented (Plan 1 Task 5). ✓

**2. Placeholders:** Full code in Tasks 1-2 (Python), Task 3 (complete HTML), Task 5 (integration test).

**3. Consistency:** `build_state_payload(run_dir) -> dict` consistent (Task 1 def + tests + Task 5 integration). `serve(eval_dir, run_id, base, port)` consistent (Task 1 def + Task 2 cli). `/api/state` endpoint consistent. `dashboard_assets/index.html` path consistent (Task 1 ASSETS_DIR + Task 3 file). Polling 1.5s consistent. Read-only (no writes) consistent.
