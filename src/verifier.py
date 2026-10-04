from __future__ import annotations

from dataclasses import fields
from typing import Any, TypeVar

from src.model import (
    Authority, Intent, Observation, Quote, SCHEMA, ServiceResult, Settlement, canonical_hash
)

T = TypeVar("T")


def _load(cls: type[T], raw: dict[str, Any]) -> T:
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in names})


def verify(proof: dict[str, Any], *, now: int, consumed_decisions: set[str] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if proof.get("schema") != SCHEMA:
        errors.append("schema-invalid")

    supplied_hash = proof.get("proof_hash")
    body = dict(proof)
    body.pop("proof_hash", None)
    if supplied_hash != canonical_hash(body):
        errors.append("proof-hash-mismatch")

    try:
        intent = _load(Intent, proof["intent"])
        quote = _load(Quote, proof["quote"])
        authority = _load(Authority, proof["authority"])
    except (KeyError, TypeError, ValueError):
        return {"verdict": "NOT VERIFIED", "errors": errors + ["core-evidence-invalid"]}

    if proof["quote"].get("digest") != quote.digest:
        errors.append("quote-digest-mismatch")
    if proof["authority"].get("digest") != authority.digest:
        errors.append("authority-digest-mismatch")
    if authority.intent_id != intent.intent_id or authority.quote_id != quote.quote_id:
        errors.append("authority-binding-mismatch")
    if intent.service_id != quote.service_id or intent.request_digest != quote.request_digest:
        errors.append("intent-quote-mismatch")
    if authority.service_id != quote.service_id:
        errors.append("service-mismatch")
    if authority.recipient != quote.recipient:
        errors.append("recipient-mismatch")
    if authority.chain_id != quote.chain_id:
        errors.append("chain-mismatch")
    if authority.asset_contract != quote.asset_contract:
        errors.append("asset-mismatch")
    if authority.decision == "PERMIT" and quote.amount_atomic > authority.maximum_amount_atomic:
        errors.append("amount-exceeds-authority")
    if now > quote.expires_at or now > authority.expires_at:
        errors.append("expired")
    if consumed_decisions is not None and authority.decision_id in consumed_decisions:
        errors.append("authority-replay")

    settlement_raw = proof.get("settlement")
    result_raw = proof.get("result")
    observation_raw = proof.get("observation")

    if authority.decision == "DENY":
        if settlement_raw is not None:
            errors.append("denied-authority-has-settlement")
        return {"verdict": "VERIFIED DENIAL" if not errors else "NOT VERIFIED", "errors": errors}

    if authority.decision != "PERMIT":
        errors.append("authority-decision-invalid")

    if not settlement_raw or not result_raw or not observation_raw:
        errors.append("incomplete-evidence")
        return {"verdict": "NOT VERIFIED", "errors": errors}

    try:
        settlement = _load(Settlement, settlement_raw)
        result = _load(ServiceResult, result_raw)
        observation = _load(Observation, observation_raw)
    except (TypeError, ValueError):
        return {"verdict": "NOT VERIFIED", "errors": errors + ["evidence-invalid"]}

    if settlement_raw.get("digest") != settlement.digest:
        errors.append("settlement-digest-mismatch")
    if result_raw.get("digest") != result.digest:
        errors.append("result-digest-mismatch")
    if observation_raw.get("digest") != observation.digest:
        errors.append("observation-digest-mismatch")

    if settlement.chain_id != authority.chain_id:
        errors.append("settlement-chain-mismatch")
    if settlement.recipient != authority.recipient:
        errors.append("settlement-recipient-mismatch")
    if settlement.asset_contract != authority.asset_contract:
        errors.append("settlement-asset-mismatch")
    if settlement.amount_atomic != quote.amount_atomic or settlement.amount_atomic > authority.maximum_amount_atomic:
        errors.append("settlement-amount-mismatch")
    if settlement.status != "FINALIZED":
        errors.append("settlement-not-finalized")
    if result.service_id != intent.service_id or result.request_digest != intent.request_digest:
        errors.append("result-binding-mismatch")
    if observation.settlement_digest != settlement.digest or observation.result_digest != result.digest:
        errors.append("observation-binding-mismatch")
    if observation.observer_id == intent.agent_id:
        errors.append("observer-not-independent")
    if observation.verdict != "MATCH":
        errors.append("observer-verdict-failed")

    return {"verdict": "VERIFIED" if not errors else "NOT VERIFIED", "errors": errors}
