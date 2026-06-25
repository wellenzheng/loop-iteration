"""End-to-end: a bespoke SSE-style agent run via an agent-authored adapter.py (start/run_case/stop).
Validates that a per-agent script in .self-iterate/ drives the per-round lifecycle (start from
worktree -> call the bespoke endpoint per case -> stop), applying the variant harness."""
import json, socket, threading, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from loop_iter.adapter_generic import build_run_case, _UserScriptAdapter
from loop_iter.case_runner import run_cases


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class _SSEHandler(BaseHTTPRequestHandler):
    """A bespoke SSE endpoint: reads <BESPOKE_WT>/mode.txt ('upper'|'lower'), emits 2 SSE data
    events then [DONE]. Each data event is JSON {"chunk": "<text>"}. The adapter must concatenate."""
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n).decode()
        try: q = json.loads(body).get("query", "")
        except Exception: q = body
        try:
            mode = open(os.path.join(os.environ["BESPOKE_WT"], "mode.txt")).read().strip()
        except Exception:
            mode = "upper"
        out = q.upper() if mode == "upper" else q.lower()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        half = len(out) // 2 or 1
        for chunk in (out[:half], out[half:]):
            self.wfile.write(f"data: {json.dumps({'chunk': chunk})}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
    def log_message(self, *a): pass


def _start_server(port):
    srv = HTTPServer(("127.0.0.1", port), _SSEHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


ADAPTER_PY = (
    "import json, os\n"
    "_port = None\n"
    "def start(worktree):\n"
    "    global _port\n"
    "    _port = int(os.environ['BESPOKE_PORT'])\n"
    "    return _port\n"
    "def run_case(case, worktree):\n"
    "    import urllib.request\n"
    "    body = json.dumps({'query': case.get('query','')}).encode()\n"
    "    try:\n"
    "        r = urllib.request.urlopen(f'http://127.0.0.1:{_port}/v1/chat', data=body, timeout=10)\n"
    "        text = r.read().decode()\n"
    "        out = ''\n"
    "        for line in text.splitlines():\n"
    "            if line.startswith('data: ') and line != 'data: [DONE]':\n"
    "                out += json.loads(line[6:])['chunk']\n"
    "        return {'case_id': case['id'], 'output': out, 'trace': {}, 'error': None}\n"
    "    except Exception as e:\n"
    "        return {'case_id': case['id'], 'output': '', 'trace': {}, 'error': f'adapter: {e!r}'}\n"
    "def stop():\n"
    "    pass\n"
)


def test_bespoke_adapter_py_drives_per_round_lifecycle(tmp_path):
    port = _free_port()
    srv = _start_server(port)
    try:
        # worktree holds mode.txt (the "variant harness"): mode=lower
        wt = tmp_path / "wt"; wt.mkdir()
        (wt / "mode.txt").write_text("lower")
        os.environ["BESPOKE_WT"] = str(wt); os.environ["BESPOKE_PORT"] = str(port)
        ev = tmp_path / "g"; ev.mkdir()
        (ev / "adapter.py").write_text(ADAPTER_PY)
        rc = build_run_case(str(ev), {"type": "custom"}, [])
        assert isinstance(rc, _UserScriptAdapter)
        gpath = str(tmp_path / "gates.py")
        with open(gpath, "w") as f:
            f.write("def lower(result, case):\n    return {'passed': result['output'] == case['query'].lower()}\nGATES={'lower':lower}\n")
        cases = [{"id": "c1", "query": "HELLO"}, {"id": "c2", "query": "WORLD"}]
        out = run_cases(cases, str(wt), gpath, "j", {"gates": 1.0},
                        run_case_fn=rc, judge_case_fn=lambda *a, **k: [])
        # the bespoke SSE was parsed + the variant harness (mode=lower from worktree) was applied
        assert out["cases"][0]["error"] is None
        assert out["cases"][0]["output"] == "hello"   # HELLO lowercased + reassembled from 2 SSE chunks
        assert out["cases"][1]["output"] == "world"
        assert out["gate_pass_rates"]["lower"] == 1.0
    finally:
        os.environ.pop("BESPOKE_WT", None); os.environ.pop("BESPOKE_PORT", None); srv.shutdown()
