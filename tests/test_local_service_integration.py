"""End-to-end: a real stdlib http.server as the 'agent', run_cases through ServiceAdapter.
Validates start (from worktree) -> POST cases -> stop, and that the variant harness dir is used
(the server reads its answer-transform from a file in the worktree)."""
import json, socket, threading, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from loop_iter.adapter_generic import build_run_case, ServiceAdapter
from loop_iter.case_runner import run_cases


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class _FileConfigHandler(BaseHTTPRequestHandler):
    """Reads <SMOKE_WT>/transform.json ({'mode':'upper'|'lower'}); answers {query} transformed."""
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n).decode()
        try: q = json.loads(body).get("query", "")
        except Exception: q = body
        try:
            cfg = json.load(open(os.path.join(os.environ["SMOKE_WT"], "transform.json")))
            mode = cfg.get("mode", "upper")
        except Exception:
            mode = "upper"
        ans = q.upper() if mode == "upper" else q.lower()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"data": {"answer": ans}}).encode())
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass


def _start_server(port):
    srv = HTTPServer(("127.0.0.1", port), _FileConfigHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_run_cases_local_service_uses_worktree_harness(tmp_path):
    port = _free_port()
    srv = _start_server(port)
    try:
        # the worktree holds a transform.json (the "variant harness"): mode=lower
        wt = tmp_path / "wt"; wt.mkdir()
        (wt / "transform.json").write_text('{"mode":"lower"}')
        os.environ["SMOKE_WT"] = str(wt)
        cfg = {"type": "local-service", "start": ["bash", "-c", "echo x"], "port": port,
               "ready": f"http://localhost:{port}/", "endpoint": f"http://localhost:{port}/v1/chat",
               "request": '{"query":"{query}"}', "response_path": "data.answer", "timeout": 10}
        adapter = build_run_case(str(tmp_path), cfg, [])
        assert isinstance(adapter, ServiceAdapter)
        # gate that checks the answer equals the lowercased query
        gpath = str(tmp_path / "gates.py")
        with open(gpath, "w") as f:
            f.write("def lower(result, case):\n"
                    "    return {'passed': result['output'] == case['query'].lower()}\n"
                    "GATES={'lower':lower}\n")
        try:
            cases = [{"id": "c1", "query": "HELLO"}, {"id": "c2", "query": "WORLD"}]
            out = run_cases(cases, str(wt), gpath, "j", {"gates": 1.0},
                            run_case_fn=adapter, judge_case_fn=lambda *a, **k: [])
            # both cases: server applied mode=lower (from worktree transform.json) -> "hello"/"world"
            assert out["cases"][0]["error"] is None
            assert out["cases"][0]["output"] == "hello"
            assert out["cases"][1]["output"] == "world"
            # the gate (lower) passes because the variant harness (mode=lower) was applied
            assert out["gate_pass_rates"]["lower"] == 1.0
        finally:
            os.environ.pop("SMOKE_WT", None)
    finally:
        if "SMOKE_WT" in os.environ:
            os.environ.pop("SMOKE_WT", None)
        srv.shutdown()
