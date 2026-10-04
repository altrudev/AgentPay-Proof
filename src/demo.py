from src.model import (
    BASE_CHAIN_ID, Intent, Observation, Quote, ServiceResult, Settlement,
    canonical_hash, decide, make_proof,
)

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def run(amount_atomic: int, *, now: int = 1_800_000_000):
    request = {"operation": "summarize-document", "document": "demo"}
    request_digest = canonical_hash(request)
    intent = Intent("intent-demo", "demo-agent", "summarize-document", request_digest, now)
    quote = Quote(
        "quote-demo", "summarize-document", "0x000000000000000000000000000000000000BEEF",
        BASE_CHAIN_ID, USDC_BASE, amount_atomic, now + 300, request_digest,
    )
    authority = decide(
        intent, quote, decision_id="decision-demo", maximum_amount_atomic=1_000_000,
        recipient=quote.recipient, service_id=quote.service_id, chain_id=BASE_CHAIN_ID,
        asset_contract=USDC_BASE, expires_at=now + 300, now=now,
    )
    if authority.decision == "DENY":
        return make_proof(intent, quote, authority)

    # Explicit fixture only: live Base settlement will replace this in P2.
    settlement = Settlement(
        BASE_CHAIN_ID, "demo:not-on-chain", "0xAgent", quote.recipient,
        USDC_BASE, amount_atomic, "FINALIZED",
    )
    result_digest = canonical_hash({"summary": "demo result"})
    result = ServiceResult(quote.service_id, request_digest, result_digest, "COMPLETE")
    observation = Observation(
        "independent-demo-observer", settlement.digest, result.digest, "MATCH", now + 1
    )
    return make_proof(intent, quote, authority, settlement, result, observation)
