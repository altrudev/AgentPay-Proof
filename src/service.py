from __future__ import annotations

from dataclasses import dataclass
import re
import time
import uuid

from src.demo import USDC_BASE
from src.model import BASE_CHAIN_ID, Quote, ServiceResult, canonical_hash

SERVICE_ID = "document-summary-v1"
SERVICE_RECIPIENT = "0x000000000000000000000000000000000000BEEF"
DEFAULT_PRICE_ATOMIC = 250_000  # 0.25 USDC at 6 decimals
QUOTE_TTL_SECONDS = 300


@dataclass(frozen=True)
class ServiceRequest:
    document: str

    @property
    def digest(self) -> str:
        return canonical_hash({"service_id": SERVICE_ID, "document": self.document})


def create_quote(request: ServiceRequest, *, now: int | None = None,
                 amount_atomic: int = DEFAULT_PRICE_ATOMIC) -> Quote:
    now = int(time.time()) if now is None else now
    if not request.document.strip():
        raise ValueError("document-required")
    return Quote(
        quote_id=f"q-{uuid.uuid4()}",
        service_id=SERVICE_ID,
        recipient=SERVICE_RECIPIENT,
        chain_id=BASE_CHAIN_ID,
        asset_contract=USDC_BASE,
        amount_atomic=amount_atomic,
        expires_at=now + QUOTE_TTL_SECONDS,
        request_digest=request.digest,
    )


def execute(request: ServiceRequest, quote: Quote, *, now: int | None = None) -> tuple[dict, ServiceResult]:
    now = int(time.time()) if now is None else now
    if quote.service_id != SERVICE_ID:
        raise PermissionError("service-binding-mismatch")
    if quote.request_digest != request.digest:
        raise PermissionError("request-binding-mismatch")
    if now > quote.expires_at:
        raise PermissionError("quote-expired")

    # Deterministic service fixture: useful enough to demonstrate paid execution
    # while keeping the verifier independent of an external LLM provider.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", request.document.strip()) if s.strip()]
    summary = " ".join(sentences[:2])
    artifact = {"service_id": SERVICE_ID, "summary": summary, "source_digest": request.digest}
    result = ServiceResult(SERVICE_ID, request.digest, canonical_hash(artifact), "COMPLETE")
    return artifact, result
