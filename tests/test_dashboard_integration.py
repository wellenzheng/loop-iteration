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
