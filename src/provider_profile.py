from __future__ import annotations

from src.model import canonical_hash


AGENTPAY_PROVIDER_ID = "provider:altru-agentpay"
AGENTPAY_PROVIDER_LEGAL_IDENTITY = "Valentyn Rukhaylo / Altru.dev (individual operator)"
AGENTPAY_PROVIDER_BRAND = "Altru.dev / AgentPay"
AGENTPAY_PROVIDER_OPERATOR_KIND = "individual"
AGENTPAY_PROVIDER_DOMAIN = "agentpay.altru.dev"
AGENTPAY_PROVIDER_BASE_URL = "https://agentpay.altru.dev"
AGENTPAY_PROVIDER_ADAPTER_URL = AGENTPAY_PROVIDER_BASE_URL + "/api/x402/code-analysis"
AGENTPAY_PROVIDER_IDENTITY_URL = AGENTPAY_PROVIDER_BASE_URL + "/api/provider/identity"
AGENTPAY_PROVIDER_CAPABILITY = "agentpay.code-analysis-v1"
AGENTPAY_PROVIDER_SERVICE_ID = "code-analysis-v1"
AGENTPAY_PROVIDER_RECIPIENT = "0xebd095378327f025e7d5852868cb7366627aadfc"
AGENTPAY_PROVIDER_CHAIN_ID = 8453
AGENTPAY_PROVIDER_ASSET = "USDC"
AGENTPAY_PROVIDER_ASSET_CONTRACT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
AGENTPAY_PROVIDER_PRICE_ATOMIC = 250000

AGENTPAY_PROVIDER_KEY_ID = "provider-key:altru-agentpay-ed25519-v1"
AGENTPAY_PROVIDER_PUBLIC_KEY_B64 = "TI2C4+qBTJ8Kpa/yjeMca9E608vAIplxK81xFk/AUfw="


def public_provider_identity() -> dict:
    document = {
        "schema": "agentpay-provider-public-identity/1",
        "provider_id": AGENTPAY_PROVIDER_ID,
        "legal_identity": AGENTPAY_PROVIDER_LEGAL_IDENTITY,
        "brand": AGENTPAY_PROVIDER_BRAND,
        "operator_kind": AGENTPAY_PROVIDER_OPERATOR_KIND,
        "domain": AGENTPAY_PROVIDER_DOMAIN,
        "adapter_url": AGENTPAY_PROVIDER_ADAPTER_URL,
        "identity_url": AGENTPAY_PROVIDER_IDENTITY_URL,
        "capability": AGENTPAY_PROVIDER_CAPABILITY,
        "service_id": AGENTPAY_PROVIDER_SERVICE_ID,
        "chain_id": AGENTPAY_PROVIDER_CHAIN_ID,
        "settlement_asset": AGENTPAY_PROVIDER_ASSET,
        "asset_contract": AGENTPAY_PROVIDER_ASSET_CONTRACT,
        "payment_recipient": AGENTPAY_PROVIDER_RECIPIENT,
        "price_atomic": AGENTPAY_PROVIDER_PRICE_ATOMIC,
        "issuer_key_id": AGENTPAY_PROVIDER_KEY_ID,
        "issuer_public_key_b64": AGENTPAY_PROVIDER_PUBLIC_KEY_B64,
    }
    return {**document, "digest": canonical_hash(document)}
