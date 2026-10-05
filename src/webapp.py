from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from src.model import Settlement
from src.observer import IndependentObserver
from src.service import ServiceRequest
from src.verifier import verify
from src.workflow import AgentPayWorkflow

WEB = Path(__file__).resolve().parent.parent / "web"


class DemoSettlementProvider:
    """Explicit non-chain fixture. Never presented as on-chain settlement."""

    def settle(self, transaction, quote, authority):
        return Settlement(
            quote.chain_id, "demo:not-on-chain",
            "0x000000000000000000000000000000000000cafe",
            quote.recipient, quote.asset_contract, quote.amount_atomic, "FINALIZED",
        )


def workflow() -> AgentPayWorkflow:
    return AgentPayWorkflow(
        settlement_provider=DemoSettlementProvider(),
        observer=IndependentObserver("observer:agentpay-demo"),
        maximum_amount_atomic=1_000_000,
    )


def run_demo(amount_atomic: int, document: str) -> dict:
    outcome = workflow().purchase(
        ServiceRequest(document), agent_id="agent:judge-demo",
        now=1_800_000_000, quote_amount_atomic=amount_atomic,
    )
    return {"environment": "DEMO", **outcome}


def tamper_demo(proof: dict) -> dict:
    copy = json.loads(json.dumps(proof))
    if copy.get("settlement"):
        copy["settlement"]["amount_atomic"] += 1
    else:
        copy["authority"]["reason"] = "tampered"
    return {"environment": "DEMO", "proof": copy, "verification": verify(copy, now=1_800_000_000)}


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentPayProof/0.1"

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("content-security-policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._json(200, {"ok": True, "environment": "DEMO"})
        name = "index.html" if path == "/" else path.lstrip("/")
        if name not in {"index.html", "app.js", "styles.css"}:
            return self._json(404, {"error": "not-found"})
        target = WEB / name
        if not target.exists():
            return self._json(404, {"error": "not-found"})
        body = target.read_bytes()
        mime = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}[name.rsplit(".",1)[-1]]
        self.send_response(200)
        self.send_header("content-type", mime)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("content-security-policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            body = json.dumps({"ok": True, "environment": "DEMO"}, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.send_header("x-content-type-options", "nosniff")
            self.end_headers()
            return
        name = "index.html" if path == "/" else path.lstrip("/")
        if name not in {"index.html", "app.js", "styles.css"}:
            self.send_response(404)
            self.end_headers()
            return
        target = WEB / name
        if not target.exists():
            self.send_response(404)
            self.end_headers()
            return
        body = target.read_bytes()
        mime = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}[name.rsplit(".",1)[-1]]
        self.send_response(200)
        self.send_header("content-type", mime)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("content-length", "0"))
            if length > 64_000:
                return self._json(413, {"error": "request-too-large"})
            payload = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/run":
                amount = int(payload.get("amount_atomic", 250_000))
                document = str(payload.get("document", ""))[:5000]
                if not document.strip() or amount <= 0 or amount > 10_000_000:
                    return self._json(400, {"error": "invalid-request"})
                return self._json(200, run_demo(amount, document))
            if path == "/api/tamper":
                proof = payload.get("proof")
                if not isinstance(proof, dict):
                    return self._json(400, {"error": "proof-required"})
                return self._json(200, tamper_demo(proof))
            return self._json(404, {"error": "not-found"})
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid-request"})

    def log_message(self, fmt, *args):
        return


def serve(host="127.0.0.1", port=8787):
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve(
        host=os.environ.get("AGENTPAY_HOST", "127.0.0.1"),
        port=int(os.environ.get("AGENTPAY_PORT", "8787")),
    )
