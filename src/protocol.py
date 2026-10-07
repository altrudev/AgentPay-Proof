from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.model import Quote
from src.service import (
    DEFAULT_PRICE_ATOMIC,
    DEFAULT_SERVICE_ID,
    SERVICE_SPECS,
    ServiceRequest,
    create_quote,
    service_catalog,
)

DISCOVERY_SCHEMA = "agentpay-service/1"


def discovery_document(service_id: str = DEFAULT_SERVICE_ID) -> dict[str, Any]:
    spec = SERVICE_SPECS[service_id]
    return {
        "schema": DISCOVERY_SCHEMA,
        "service_id": service_id,
        "title": spec["title"],
        "description": spec["description"],
        "quote": {
            "method": "POST",
            "path": "/api/live/prepare",
            "request_content_type": "application/json",
            "price_asset": "USDC",
            "price_atomic": spec["price_atomic"],
            "asset_decimals": 6,
        },
        "execute": {
            "method": "POST",
            "path": "/api/live/reconcile",
            "requires": ["accepted_quote", "authorized_settlement_evidence"],
        },
    }


def catalog_document() -> dict[str, Any]:
    return {
        "schema": "agentpay-catalog/1",
        "services": service_catalog(),
    }


def quote_document(
    request: ServiceRequest,
    *,
    now: int,
    amount_atomic: int | None = None,
) -> dict[str, Any]:
    quote = create_quote(request, now=now, amount_atomic=amount_atomic)
    return {
        "schema": "agentpay-quote/1",
        "request": {"service_id": request.service_id, "request_digest": request.digest},
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
