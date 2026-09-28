"""Zero-dependency HTTP server: python server.py  ->  http://localhost:8000"""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from agent.data import ERP
from agent.agent import PurchasingAgent

ERP_STATE = ERP()
PENDING = {}  # sku -> decision awaiting human approval


def run_agent():
    a, mode = PurchasingAgent(ERP_STATE), "policy"
    res = None
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            from agent.llm_agent import run_llm
            res, mode = run_llm(a, anthropic.Anthropic(), os.getenv("MODEL", "claude-sonnet-4-5")), "llm"
        except Exception as e:
            a.log("error", f"LLM mode failed ({type(e).__name__}); falling back to policy mode")
    if res is None:
        res = a.run()
    for r in res:
        if r["status"] == "pending_approval":
            PENDING[r["decision"]["sku"]] = r["decision"]
    return {"mode": mode, "results": res, "trace": a.trace, "budget": ERP_STATE.db["budget"], "pos": ERP_STATE.pos}


def approve(sku, approved):
    d = PENDING.pop(sku, None)
    if not d:
        return {"error": "nothing pending for " + sku}
    if not approved:
        return {"status": "rejected", "sku": sku}
    a = PurchasingAgent(ERP_STATE)
    out = a.execute(d)
    return {"status": "executed", **out, "trace": a.trace, "budget": ERP_STATE.db["budget"]}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p = os.path.join(os.path.dirname(__file__), "static", "index.html")
        self._send(200, open(p, "rb").read(), "text/html") if self.path == "/" else self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/run":
            self._send(200, run_agent())
        elif self.path == "/api/approve":
            self._send(200, approve(body.get("sku"), body.get("approved", False)))
        elif self.path == "/api/reset":
            global ERP_STATE
            ERP_STATE, _ = ERP(), PENDING.clear()
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})


if __name__ == "__main__":
    print("Serving on http://localhost:8000")
    HTTPServer(("", 8000), H).serve_forever()
