from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.model import Quote
from src.service import DEFAULT_PRICE_ATOMIC, SERVICE_ID, ServiceRequest, create_quote

DISCOVERY_SCHEMA = "agentpay-service/1"


def discovery_document() -> dict[str, Any]:
    return {
        "schema": DISCOVERY_SCHEMA,
        "service_id": SERVICE_ID,
        "description": "Deterministic document summarization for AgentPay Proof",
        "quote": {
            "method": "POST",
            "path": "/quote",
            "request_content_type": "application/json",
            "price_asset": "USDC",
            "price_atomic": DEFAULT_PRICE_ATOMIC,
            "asset_decimals": 6,
        },
        "execute": {
            "method": "POST",
            "path": "/execute",
            "requires": ["accepted_quote", "authorized_settlement_evidence"],
        },
    }


def quote_document(request: ServiceRequest, *, now: int, amount_atomic: int = DEFAULT_PRICE_ATOMIC) -> dict[str, Any]:
    quote = create_quote(request, now=now, amount_atomic=amount_atomic)
    return {
        "schema": "agentpay-quote/1",
        "request": {"service_id": SERVICE_ID, "request_digest": request.digest},
        "quote": {**asdict(quote), "digest": quote.digest},
    }


def load_quote(document: dict[str, Any]) -> Quote:
    if document.get("schema") != "agentpay-quote/1":
        raise ValueError("quote-schema-invalid")
    raw = document.get("quote")
    if not isinstance(raw, dict):
        raise ValueError("quote-invalid")
    fields = {k: v for k, v in raw.items() if k != "digest"}
    quote = Quote(**fields)
    if raw.get("digest") != quote.digest:
        raise ValueError("quote-digest-invalid")
    request = document.get("request", {})
    if request.get("request_digest") != quote.request_digest or request.get("service_id") != quote.service_id:
        raise ValueError("quote-request-binding-invalid")
    return quote
