"""Real-time dashboard: a stdlib HTTP server that serves a SPA + /api/state (merging the run dir).
Read-only view over the state machine's writes — never drives the loop."""
from __future__ import annotations
import json
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
                  "baseline_quality", "best", "goal", "run_id", "started_at", "updated_at",
                  "quality_target"):
            if k in state:
                payload[k] = state[k]

    baseline_path = run_dir / "baseline.json"
    if baseline_path.exists():
        b = json.loads(baseline_path.read_text())
        payload["baseline"] = {
            "composite": b.get("composite"), "gate_pass_rates": b.get("gate_pass_rates"),
            "quality": b.get("quality"), "quality_dims": b.get("quality_dims"),
            "cases": b.get("cases")}

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
        pass


def serve(eval_dir: str, run_id: str, base: str = ".", port: int = 0):
    """Start the dashboard HTTP server. port=0 = auto-pick. Blocks (run in background)."""
    from loop_iter.state import RunPaths
    rp = RunPaths(base=base, run_id=run_id)
    run_dir = rp.run_dir
    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.run_dir = run_dir  # type: ignore
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"
    print(json.dumps({"url": url, "port": actual_port, "run_dir": str(run_dir)}))
    import webbrowser
    webbrowser.open(url)
    server.serve_forever()
