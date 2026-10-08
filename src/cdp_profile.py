from __future__ import annotations

CDP_FACILITATOR_ID = "facilitator:coinbase-cdp-x402-v2"
CDP_FACILITATOR_BASE_URL = "https://api.cdp.coinbase.com/platform/v2/x402"
CDP_VERIFY_URL = CDP_FACILITATOR_BASE_URL + "/verify"
CDP_SETTLE_URL = CDP_FACILITATOR_BASE_URL + "/settle"
CDP_SUPPORTED_URL = CDP_FACILITATOR_BASE_URL + "/supported"

# Reviewed independent observation from docs/evidence/cdp-facilitator-probe-2026-10-07.json.
# Rotation is deliberately fail-closed: a changed SPKI requires a new observation,
# review, evidence artifact and profile update.
CDP_REVIEWED_TLS_SPKI_SHA256 = (
    "sha256:3629e1923cd6465df7c6621eec65e2931e3da959add4a868c85dcf4f3e3f20ca"
)

CDP_X402_VERSION = 2
CDP_SCHEME = "exact"
CDP_BASE_NETWORK = "eip155:8453"
CDP_BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

CDP_SQL_RESOURCE_URL = "https://x402.cdp.coinbase.com/platform/v2/data/query/run"
CDP_SQL_CANARY_REQUEST = {
    "sql": "SELECT block_number FROM base.blocks ORDER BY block_number DESC LIMIT 1"
}
CDP_SQL_EXPECTED_AMOUNT_ATOMIC = 100000
