from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.model import Intent, Settlement, decide, make_proof
from src.observer import IndependentObserver
from src.protocol import quote_document, load_quote
from src.service import ServiceRequest, execute
from src.settlement import transaction_request
from src.verifier import verify


class SettlementProvider(Protocol):
    def settle(self, transaction: dict, quote, authority) -> Settlement: ...


@dataclass
class AgentPayWorkflow:
    settlement_provider: SettlementProvider
    observer: IndependentObserver
    maximum_amount_atomic: int
    decision_ttl_seconds: int = 300

    def purchase(self, request: ServiceRequest, *, agent_id: str, now: int,
                 quote_amount_atomic: int | None = None) -> dict:
        qdoc = quote_document(
            request,
            now=now,
            **({"amount_atomic": quote_amount_atomic} if quote_amount_atomic is not None else {}),
        )
        quote = load_quote(qdoc)
        intent = Intent(
            intent_id="intent:" + request.digest[:24],
            agent_id=agent_id,
            service_id=quote.service_id,
            request_digest=request.digest,
            created_at=now,
        )
        authority = decide(
            intent,
            quote,
            decision_id="decision:" + quote.digest[:24],
            maximum_amount_atomic=self.maximum_amount_atomic,
            recipient=quote.recipient,
            service_id=quote.service_id,
            chain_id=quote.chain_id,
            asset_contract=quote.asset_contract,
            expires_at=min(quote.expires_at, now + self.decision_ttl_seconds),
            now=now,
        )
        if authority.decision == "DENY":
            proof = make_proof(intent, quote, authority)
            return {
                "status": "DENIED",
                "proof": proof,
                "verification": verify(proof, now=now),
                "transaction_request": None,
            }

        tx_request = transaction_request(authority, quote, now=now)
        settlement = self.settlement_provider.settle(tx_request, quote, authority)
        artifact, result = execute(request, quote, now=now)
        observation = self.observer.observe(
            settlement=settlement, result=result, artifact=artifact, now=now
        )
        proof = make_proof(intent, quote, authority, settlement, result, observation)
        return {
            "status": "VERIFIED" if verify(proof, now=now)["verdict"] == "VERIFIED" else "NOT VERIFIED",
            "proof": proof,
            "verification": verify(proof, now=now),
            "transaction_request": tx_request,
            "artifact": artifact,
        }
