from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cdp_auth import CdpApiKey, CdpAuthError, CdpBearerTokenProvider
from src.cdp_profile import (
    CDP_BASE_NETWORK,
    CDP_FACILITATOR_BASE_URL,
    CDP_FACILITATOR_ID,
    CDP_REVIEWED_TLS_SPKI_SHA256,
    CDP_SCHEME,
    CDP_SQL_CANARY_REQUEST,
    CDP_SQL_EXPECTED_AMOUNT_ATOMIC,
    CDP_SQL_RESOURCE_URL,
    CDP_SUPPORTED_URL,
    CDP_X402_VERSION,
)
from src.facilitator_capability import (
    capability_evidence_from_supported,
    require_supported_scope,
)
from src.facilitator_client import FacilitatorRuntimeConfig, HTTPX402Facilitator
from src.facilitator_probe import FacilitatorProbeTarget, probe_facilitator_transport
from src.x402_resource_probe import probe_x402_resource


def main() -> int:
    now = int(time.time())
    result: dict = {
        "schema": "agentpay-cdp-readiness/1",
        "observed_at": now,
        "facilitator_id": CDP_FACILITATOR_ID,
        "production_authority": False,
        "wallet_signing_enabled": False,
        "settlement_enabled": False,
        "checks": {},
        "blockers": [],
    }

    transport = probe_facilitator_transport(
        FacilitatorProbeTarget(
            facilitator_id=CDP_FACILITATOR_ID,
            verify_url=CDP_FACILITATOR_BASE_URL + "/verify",
            settle_url=CDP_FACILITATOR_BASE_URL + "/settle",
        ),
        observer="frequency:cdp-readiness",
        observed_at=now,
    )
    result["checks"]["transport"] = {
        "status": "PASS"
        if transport.tls_spki_sha256 == CDP_REVIEWED_TLS_SPKI_SHA256
        else "FAIL",
        "evidence": asdict(transport),
        "digest": transport.digest,
    }
    if transport.tls_spki_sha256 != CDP_REVIEWED_TLS_SPKI_SHA256:
        result["blockers"].append("cdp-reviewed-spki-mismatch")

    quote = probe_x402_resource(
        resource_url=CDP_SQL_RESOURCE_URL,
        request_body=CDP_SQL_CANARY_REQUEST,
        observer="frequency:cdp-readiness",
        observed_at=now,
    )
    accepted = quote.payment_required["accepts"]
    exact = [
        item
        for item in accepted
        if isinstance(item, dict)
        and item.get("scheme") == CDP_SCHEME
        and item.get("network") == CDP_BASE_NETWORK
        and int(str(item.get("amount", "0"))) == CDP_SQL_EXPECTED_AMOUNT_ATOMIC
    ]
    result["checks"]["resource_quote"] = {
        "status": "PASS" if len(exact) == 1 else "FAIL",
        "digest": quote.digest,
        "payment_required_digest": quote.payment_required_digest,
        "payment_required": quote.payment_required,
    }
    if len(exact) != 1:
        result["blockers"].append("cdp-sql-canary-quote-mismatch")

    try:
        api_key = CdpApiKey.from_environment()
    except CdpAuthError:
        result["checks"]["authenticated_supported"] = {
            "status": "BLOCKED",
            "reason": "cdp-api-key-environment-unavailable",
        }
        result["blockers"].append("cdp-authenticated-supported-proof-missing")
    else:
        client = HTTPX402Facilitator(
            FacilitatorRuntimeConfig(
                facilitator_id=CDP_FACILITATOR_ID,
                base_url=CDP_FACILITATOR_BASE_URL,
                tls_spki_sha256=CDP_REVIEWED_TLS_SPKI_SHA256,
            ),
            token_provider=CdpBearerTokenProvider(api_key),
        )
        supported = client.supported()
        capability = capability_evidence_from_supported(
            facilitator_id=CDP_FACILITATOR_ID,
            supported_url=CDP_SUPPORTED_URL,
            response=supported,
            observer="frequency:cdp-authenticated-supported",
            observed_at=now,
            valid_until=now + 600,
            x402_version=CDP_X402_VERSION,
        )
        require_supported_scope(
            capability,
            scheme=CDP_SCHEME,
            network=CDP_BASE_NETWORK,
        )
        result["checks"]["authenticated_supported"] = {
            "status": "PASS",
            "evidence": asdict(capability),
            "digest": capability.digest,
        }

    # Deliberately not attempted by this readiness command.
    result["checks"]["authenticated_verify_semantics"] = {
        "status": "BLOCKED",
        "reason": "requires-bounded-invalid-payment-test",
    }
    result["checks"]["controlled_settlement"] = {
        "status": "BLOCKED",
        "reason": "requires-explicit-wallet-authorization-and-value-spend",
    }
    result["checks"]["provider_admission"] = {
        "status": "BLOCKED",
        "reason": "requires-provider-signed-manifest-and-independent-recipient-control",
    }
    result["blockers"].extend(
        [
            "authenticated-verify-read-only-proof-missing",
            "controlled-settlement-proof-missing",
            "real-provider-admission-missing",
        ]
    )

    result["ready_for_wallet_authorization"] = not any(
        blocker
        for blocker in result["blockers"]
        if blocker
        not in {
            "controlled-settlement-proof-missing",
        }
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if not result["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
