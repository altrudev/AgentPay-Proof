from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.live import LiveConfig, LiveCoordinator, LivePaymentError
from src.commercial_demo import release_validation_demo, release_validation_objects
from src.commercial_execution import (
    CommercialCoordinator,
    CommercialExecutionError,
    CommercialExecutionJournal,
)
from src.commercial_live import CommercialLiveError, PaidCommercialCoordinator
from src.execution import ExecutionJournal
from src.execution import ExecutionStateError
from src.model import Settlement
from src.observer import IndependentObserver
from src.protocol import catalog_document, discovery_document
from src.service import ServiceRequest, resolve_service_id
from src.verifier import verify
from src.settlement import JsonRpcClient, SettlementError
from src.workflow import AgentPayWorkflow

WEB = Path(__file__).resolve().parent.parent / "web"


def live_config() -> LiveConfig | None:
    rpc = os.environ.get("BASE_RPC_URL", "").strip()
    recipient = os.environ.get("AGENTPAY_RECIPIENT_ADDRESS", "").strip()
    token = os.environ.get("AGENTPAY_USDC_ADDRESS", "").strip()
    if not (rpc and recipient and token):
        return None
    try:
        return LiveConfig(
            rpc_url=rpc,
            journal_path=os.environ.get("AGENTPAY_STATE_DB", "agentpay-state/live.sqlite3"),
            chain_id=int(os.environ.get("AGENTPAY_CHAIN_ID", "8453")),
            asset_contract=token,
            recipient=recipient,
            maximum_amount_atomic=int(os.environ.get("AGENTPAY_MAX_AMOUNT_ATOMIC", "1000000")),
        ).validate()
    except (ValueError, LivePaymentError):
        return None


def live_coordinator() -> LiveCoordinator:
    config = live_config()
    if config is None:
        raise LivePaymentError("live-mode-not-configured")
    Path(config.journal_path).parent.mkdir(parents=True, exist_ok=True)
    return LiveCoordinator(config)


def commercial_journal() -> CommercialExecutionJournal:
    path = os.environ.get(
        "AGENTPAY_COMMERCIAL_STATE_DB",
        "agentpay-state/commercial.sqlite3",
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return CommercialExecutionJournal(path)


def commercial_coordinator() -> CommercialCoordinator:
    return CommercialCoordinator(commercial_journal())


def paid_commercial_coordinator() -> PaidCommercialCoordinator:
    config = live_config()
    if config is None:
        raise CommercialLiveError("live-mode-not-configured")
    Path(config.journal_path).parent.mkdir(parents=True, exist_ok=True)
    return PaidCommercialCoordinator(
        commercial_journal=commercial_journal(),
        payment_journal=ExecutionJournal(config.journal_path),
        live_config=config,
    )


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


def run_demo(amount_atomic: int, document: str, service_id: str = "code-analysis-v1") -> dict:
    outcome = workflow().purchase(
        ServiceRequest(document, resolve_service_id(service_id)), agent_id="agent:judge-demo",
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
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            config = live_config()
            return self._json(200, {
                "ok": True,
                "environment": "DEMO",
                "live_enabled": config is not None,
                "live_chain_id": config.chain_id if config else None,
            })
        if path == "/api/catalog":
            return self._json(200, catalog_document())
        if path == "/api/commercial/demo":
            return self._json(200, release_validation_demo(now=int(time.time())))
        if path == "/api/commercial/prepare-demo":
            now = int(time.time())
            capsule, offers = release_validation_objects(now=now)
            return self._json(200, commercial_coordinator().prepare(capsule, offers, now=now))
        if path == "/api/discovery":
            query = parse_qs(parsed.query)
            service_id = str(query.get("service_id", ["code-analysis-v1"])[0])
            try:
                service_id = resolve_service_id(service_id)
                return self._json(200, discovery_document(service_id))
            except ValueError:
                return self._json(404, {"error": "service-not-found"})
        if path == "/api/live/config":
            config = live_config()
            return self._json(200, {
                "enabled": config is not None,
                "chain_id": config.chain_id if config else None,
                "maximum_amount_atomic": config.maximum_amount_atomic if config else None,
            })
        if path == "/api/live/network":
            config = live_config()
            if config is None:
                return self._json(503, {"error": "live-mode-not-configured"})
            started = time.perf_counter()
            try:
                rpc = JsonRpcClient(config.rpc_url, timeout_seconds=5)
                chain_hex = rpc.call("eth_chainId", [])
                block_hex = rpc.call("eth_blockNumber", [])
                gas_hex = rpc.call("eth_gasPrice", [])
                latency_ms = round((time.perf_counter() - started) * 1000)
                chain_id = int(chain_hex, 16)
                if chain_id != config.chain_id:
                    return self._json(502, {"error": "rpc-network-mismatch"})
                return self._json(200, {
                    "online": True,
                    "chain_id": chain_id,
                    "block": int(block_hex, 16),
                    "gas_gwei": round(int(gas_hex, 16) / 1_000_000_000, 4),
                    "rpc_ms": latency_ms,
                })
            except Exception:
                return self._json(502, {"online": False, "error": "rpc-unavailable"})
        name = "index.html" if path == "/" else path.lstrip("/")
        allowed = {"index.html", "app.js", "styles.css", "agentpay-logo.webp", "agentpay-logo-transparent.png", "agentpay-mark.png", "agentpay-wordmark.png"}
        is_graphic = name.startswith("graphics/") and name.endswith(".svg") and ".." not in Path(name).parts
        is_approved = name.startswith("approved/") and name.endswith(".png") and ".." not in Path(name).parts
        is_v5_asset = name.startswith("assets/approved-v5/") and name.endswith((".png", ".svg")) and ".." not in Path(name).parts
        is_v6_asset = name.startswith("assets/approved-v6/") and name.endswith((".png", ".svg", ".webp")) and ".." not in Path(name).parts
        if name not in allowed and not is_graphic and not is_approved and not is_v5_asset and not is_v6_asset:
            return self._json(404, {"error": "not-found"})
        target = (WEB / name).resolve()
        if WEB.resolve() not in target.parents and target != WEB.resolve():
            return self._json(404, {"error": "not-found"})
        if not target.exists():
            return self._json(404, {"error": "not-found"})
        body = target.read_bytes()
        mime = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8", "css": "text/css; charset=utf-8", "webp": "image/webp", "png": "image/png", "svg": "image/svg+xml"}[name.rsplit(".",1)[-1]]
        self.send_response(200)
        self.send_header("content-type", mime)
        self.send_header("content-length", str(len(body)))
        cache = "public, max-age=86400, immutable" if is_graphic or is_v5_asset or is_v6_asset or name.endswith((".png", ".webp")) else "no-store"
        self.send_header("cache-control", cache)
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
        allowed = {"index.html", "app.js", "styles.css", "agentpay-logo.webp", "agentpay-logo-transparent.png", "agentpay-mark.png", "agentpay-wordmark.png"}
        is_graphic = name.startswith("graphics/") and name.endswith(".svg") and ".." not in Path(name).parts
        is_approved = name.startswith("approved/") and name.endswith(".png") and ".." not in Path(name).parts
        is_v5_asset = name.startswith("assets/approved-v5/") and name.endswith((".png", ".svg")) and ".." not in Path(name).parts
        is_v6_asset = name.startswith("assets/approved-v6/") and name.endswith((".png", ".svg", ".webp")) and ".." not in Path(name).parts
        if name not in allowed and not is_graphic and not is_approved and not is_v5_asset and not is_v6_asset:
            self.send_response(404)
            self.end_headers()
            return
        target = (WEB / name).resolve()
        if WEB.resolve() not in target.parents and target != WEB.resolve():
            self.send_response(404)
            self.end_headers()
            return
        if not target.exists():
            self.send_response(404)
            self.end_headers()
            return
        body = target.read_bytes()
        mime = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8", "css": "text/css; charset=utf-8", "webp": "image/webp", "png": "image/png", "svg": "image/svg+xml"}[name.rsplit(".",1)[-1]]
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
                service_id = str(payload.get("service_id", "code-analysis-v1"))
                if not document.strip() or amount <= 0 or amount > 10_000_000:
                    return self._json(400, {"error": "invalid-request"})
                return self._json(200, run_demo(amount, document, service_id))
            if path == "/api/tamper":
                proof = payload.get("proof")
                if not isinstance(proof, dict):
                    return self._json(400, {"error": "proof-required"})
                return self._json(200, tamper_demo(proof))
            if path == "/api/commercial/live/prepare":
                grant_id = str(payload.get("grant_id", ""))
                approval_digest = str(payload.get("approval_digest", ""))
                rendered_page_digest = str(payload.get("rendered_page_digest", ""))
                reference_digest = str(payload.get("reference_digest", ""))
                if not all((grant_id, approval_digest, rendered_page_digest, reference_digest)):
                    return self._json(400, {"error": "commercial-wallet-fields-required"})
                return self._json(200, paid_commercial_coordinator().prepare_wallet(
                    grant_id,
                    commercial_approval_digest=approval_digest,
                    payload={
                        "rendered_page_digest": rendered_page_digest,
                        "reference_digest": reference_digest,
                    },
                    now=int(time.time()),
                ))
            if path == "/api/commercial/live/abort":
                grant_id = str(payload.get("grant_id", ""))
                decision_id = str(payload.get("payment_decision_id", ""))
                if not (grant_id and decision_id):
                    return self._json(400, {"error": "commercial-wallet-abort-fields-required"})
                return self._json(200, paid_commercial_coordinator().abort_wallet(
                    grant_id, decision_id
                ))
            if path == "/api/commercial/live/uncertain":
                grant_id = str(payload.get("grant_id", ""))
                decision_id = str(payload.get("payment_decision_id", ""))
                if not (grant_id and decision_id):
                    return self._json(400, {"error": "commercial-wallet-uncertain-fields-required"})
                return self._json(200, paid_commercial_coordinator().mark_wallet_uncertain(
                    grant_id, decision_id
                ))
            if path == "/api/commercial/live/reconcile":
                grant_id = str(payload.get("grant_id", ""))
                decision_id = str(payload.get("payment_decision_id", ""))
                tx_hash = str(payload.get("transaction_hash", ""))
                sender = str(payload.get("sender", ""))
                if not all((grant_id, decision_id, tx_hash, sender)):
                    return self._json(400, {"error": "commercial-wallet-reconcile-fields-required"})
                try:
                    return self._json(200, paid_commercial_coordinator().reconcile(
                        grant_id,
                        decision_id,
                        tx_hash,
                        sender,
                        now=int(time.time()),
                    ))
                except CommercialLiveError as exc:
                    if str(exc) == "commercial-settlement-not-observed":
                        return self._json(409, {
                            "error": "commercial-settlement-not-observed",
                            "state": "IN_DOUBT",
                            "retry": "reconcile-only",
                        })
                    raise
            if path == "/api/commercial/execute-demo":
                grant_id = str(payload.get("grant_id", ""))
                approval_digest = str(payload.get("approval_digest", ""))
                rendered_page_digest = str(payload.get("rendered_page_digest", ""))
                reference_digest = str(payload.get("reference_digest", ""))
                if not all((grant_id, approval_digest, rendered_page_digest, reference_digest)):
                    return self._json(400, {"error": "commercial-execution-fields-required"})
                return self._json(200, commercial_coordinator().approve_and_execute_reference(
                    grant_id,
                    approval_digest=approval_digest,
                    payload={
                        "rendered_page_digest": rendered_page_digest,
                        "reference_digest": reference_digest,
                    },
                    now=int(time.time()),
                ))
            if path == "/api/live/prepare":
                raw_amount = payload.get("amount_atomic")
                amount = None if raw_amount in (None, "") else int(raw_amount)
                document = str(payload.get("document", ""))[:5000]
                service_id = str(payload.get("service_id", "code-analysis-v1"))
                if not document.strip() or (amount is not None and (amount <= 0 or amount > 10_000_000)):
                    return self._json(400, {"error": "invalid-request"})
                return self._json(200, live_coordinator().prepare(
                    document,
                    amount_atomic=amount,
                    agent_id="agent:browser-wallet",
                    service_id=service_id,
                ))
            if path == "/api/live/abort":
                decision_id = str(payload.get("decision_id", ""))
                if not decision_id:
                    return self._json(400, {"error": "decision-id-required"})
                return self._json(200, live_coordinator().abort(decision_id))
            if path == "/api/live/uncertain":
                decision_id = str(payload.get("decision_id", ""))
                if not decision_id:
                    return self._json(400, {"error": "decision-id-required"})
                coordinator = live_coordinator()
                record = coordinator.journal.get(decision_id)
                if record.state == "PREPARED":
                    record = coordinator.journal.mark_in_doubt(decision_id)
                return self._json(200, {
                    "environment": "LIVE", "decision_id": decision_id, "state": record.state
                })
            if path == "/api/live/reconcile":
                decision_id = str(payload.get("decision_id", ""))
                tx_hash = str(payload.get("transaction_hash", ""))
                sender = str(payload.get("sender", ""))
                if not (decision_id and tx_hash and sender):
                    return self._json(400, {"error": "reconciliation-fields-required"})
                try:
                    result = live_coordinator().reconcile(decision_id, tx_hash, sender)
                except LivePaymentError as exc:
                    if str(exc) == "settlement-not-observed":
                        return self._json(409, {
                            "error": "settlement-not-observed",
                            "state": "IN_DOUBT",
                            "retry": "reconcile-only",
                        })
                    raise
                return self._json(200, result)
            return self._json(404, {"error": "not-found"})
        except (LivePaymentError, ExecutionStateError, CommercialExecutionError, CommercialLiveError) as exc:
            return self._json(409, {"error": str(exc)})
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
