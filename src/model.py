from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

SCHEMA = "agentpay-proof/1"
BASE_CHAIN_ID = 8453


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Intent:
    intent_id: str
    agent_id: str
    service_id: str
    request_digest: str
    created_at: int


@dataclass(frozen=True)
class Quote:
    quote_id: str
    service_id: str
    recipient: str
    chain_id: int
    asset_contract: str
    amount_atomic: int
    expires_at: int
    request_digest: str

    @property
    def digest(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class Authority:
    decision_id: str
    decision: str
    intent_id: str
    quote_id: str
    maximum_amount_atomic: int
    recipient: str
    service_id: str
    chain_id: int
    asset_contract: str
    expires_at: int
    reason: str

    @property
    def digest(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class Settlement:
    chain_id: int
    transaction_hash: str
    sender: str
    recipient: str
    asset_contract: str
    amount_atomic: int
    status: str

    @property
    def digest(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class ServiceResult:
    service_id: str
    request_digest: str
    result_digest: str
    status: str

    @property
    def digest(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class Observation:
    observer_id: str
    settlement_digest: str
    result_digest: str
    verdict: str
    observed_at: int

    @property
    def digest(self) -> str:
        return canonical_hash(asdict(self))


def decide(intent: Intent, quote: Quote, *, decision_id: str, maximum_amount_atomic: int,
           recipient: str, service_id: str, chain_id: int, asset_contract: str,
           expires_at: int, now: int) -> Authority:
    checks = [
        (intent.service_id == quote.service_id == service_id, "service-mismatch"),
        (intent.request_digest == quote.request_digest, "request-mismatch"),
        (quote.recipient == recipient, "recipient-mismatch"),
        (quote.chain_id == chain_id, "chain-mismatch"),
        (quote.asset_contract == asset_contract, "asset-mismatch"),
        (quote.amount_atomic <= maximum_amount_atomic, "amount-exceeds-authority"),
        (now <= quote.expires_at and now <= expires_at, "expired"),
    ]
    failure = next((reason for ok, reason in checks if not ok), None)
    return Authority(
        decision_id, "DENY" if failure else "PERMIT", intent.intent_id, quote.quote_id,
        maximum_amount_atomic, recipient, service_id, chain_id, asset_contract,
        expires_at, failure or "within-boundary",
    )


def make_proof(intent: Intent, quote: Quote, authority: Authority,
               settlement: Settlement | None = None,
               result: ServiceResult | None = None,
               observation: Observation | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "intent": asdict(intent),
        "quote": {**asdict(quote), "digest": quote.digest},
        "authority": {**asdict(authority), "digest": authority.digest},
        "settlement": ({**asdict(settlement), "digest": settlement.digest} if settlement else None),
        "result": ({**asdict(result), "digest": result.digest} if result else None),
        "observation": ({**asdict(observation), "digest": observation.digest} if observation else None),
    }
    body["proof_id"] = canonical_hash({
        "intent_id": intent.intent_id,
        "quote_id": quote.quote_id,
        "decision_id": authority.decision_id,
    })
    body["proof_hash"] = canonical_hash(body)
    return body
