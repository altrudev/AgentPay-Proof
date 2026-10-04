from __future__ import annotations
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib, json, uuid

@dataclass(frozen=True)
class Intent:
    agent: str
    service: str
    recipient: str
    amount_usdc: str
    chain: str = "base"
    asset: str = "USDC"

@dataclass(frozen=True)
class Authority:
    decision: str
    max_usdc: str
    recipient: str
    service: str
    reason: str

@dataclass(frozen=True)
class Observation:
    observer: str
    outcome: str
    result_hash: str


def decide(intent: Intent, max_usdc: str, recipient: str, service: str) -> Authority:
    permitted = (intent.chain == "base" and intent.asset == "USDC" and
                 intent.recipient == recipient and intent.service == service and
                 Decimal(intent.amount_usdc) <= Decimal(max_usdc))
    return Authority("PERMIT" if permitted else "DENY", max_usdc, recipient, service,
                     "within-boundary" if permitted else "authority-boundary-violation")


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def make_receipt(intent: Intent, authority: Authority, settlement: dict | None,
                 result: dict | None, observation: Observation | None) -> dict:
    body = {
        "schema": "agentpay-proof/1",
        "proof_id": str(uuid.uuid4()),
        "intent": asdict(intent),
        "authority": asdict(authority),
        "settlement": settlement,
        "result": result,
        "observation": asdict(observation) if observation else None,
    }
    body["proof_hash"] = canonical_hash(body)
    return body
