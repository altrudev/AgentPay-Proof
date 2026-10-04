from src.model import Intent, Observation, canonical_hash, decide, make_receipt

def run(amount: str):
    intent = Intent("demo-agent", "summarize-document", "0xService", amount)
    authority = decide(intent, "1.00", "0xService", "summarize-document")
    if authority.decision == "DENY":
        return make_receipt(intent, authority, None, None, None)
    # Test/demo settlement reference. Live Base USDC adapter is added separately.
    settlement = {"chain":"base", "asset":"USDC", "status":"DEMO_SETTLED", "tx_hash":"demo:base-usdc"}
    result = {"status":"complete", "artifact":"summary.txt"}
    observation = Observation("independent-demo-observer", "MATCH", canonical_hash(result))
    return make_receipt(intent, authority, settlement, result, observation)
