from __future__ import annotations

from src.facilitator_admission import (
    FacilitatorBinding,
    FacilitatorRegistry,
    FacilitatorTransportProof,
)
from src.facilitator_capability import capability_evidence_from_supported, require_supported_scope
from src.facilitator_client import FacilitatorRuntimeConfig, HTTPX402Facilitator
from src.facilitator_probe import FacilitatorProbeTarget, probe_facilitator_transport
from src.x402 import BASE_MAINNET_CHAIN_ID, BASE_USDC


XPAY_FACILITATOR_ID = "facilitator:xpay-public-v2"
XPAY_LEGAL_IDENTITY = "Agentically Inc. (d/b/a xpay)"
XPAY_BASE_URL = "https://facilitator.xpay.sh"
XPAY_HOST = "facilitator.xpay.sh"
XPAY_REVIEWED_TLS_SPKI_SHA256 = (
    "sha256:eeaf2b1e73487d6475908791d62497110d2cfe680ecbd907db10feacbe1381de"
)
XPAY_NETWORK = f"eip155:{BASE_MAINNET_CHAIN_ID}"
XPAY_SCHEME = "exact"


class XPayRuntimeError(RuntimeError):
    pass


def build_xpay_runtime(
    *,
    now: int,
    observer: str = "frequency:xpay-runtime-probe",
    timeout_seconds: float = 8.0,
) -> tuple[FacilitatorRegistry, HTTPX402Facilitator, str]:
    target = FacilitatorProbeTarget(
        facilitator_id=XPAY_FACILITATOR_ID,
        verify_url=XPAY_BASE_URL + "/verify",
        settle_url=XPAY_BASE_URL + "/settle",
    )
    evidence = probe_facilitator_transport(
        target,
        observer=observer,
        observed_at=now,
        timeout=timeout_seconds,
    )
    if evidence.tls_spki_sha256 != XPAY_REVIEWED_TLS_SPKI_SHA256:
        raise XPayRuntimeError("xpay-reviewed-spki-mismatch")
    if evidence.verify_unauthenticated_status != 400:
        raise XPayRuntimeError("xpay-verify-public-boundary-changed")
    if evidence.settle_unauthenticated_status != 400:
        raise XPayRuntimeError("xpay-settle-public-boundary-changed")

    client = HTTPX402Facilitator(
        FacilitatorRuntimeConfig(
            facilitator_id=XPAY_FACILITATOR_ID,
            base_url=XPAY_BASE_URL,
            tls_spki_sha256=XPAY_REVIEWED_TLS_SPKI_SHA256,
            timeout_seconds=timeout_seconds,
        )
    )
    supported = client.supported()
    capability = capability_evidence_from_supported(
        facilitator_id=XPAY_FACILITATOR_ID,
        supported_url=client.supported_url,
        response=supported,
        observer=observer,
        observed_at=now,
        valid_until=now + 600,
        x402_version=2,
        authenticated=False,
        access_model="public",
    )
    require_supported_scope(capability, scheme=XPAY_SCHEME, network=XPAY_NETWORK)

    binding = FacilitatorBinding(
        facilitator_id=XPAY_FACILITATOR_ID,
        legal_identity=XPAY_LEGAL_IDENTITY,
        verify_url=client.verify_url,
        settle_url=client.settle_url,
        schemes=(XPAY_SCHEME,),
        networks=(XPAY_NETWORK,),
        asset_contracts=(BASE_USDC,),
        dns_names=(XPAY_HOST,),
        tls_spki_sha256=(XPAY_REVIEWED_TLS_SPKI_SHA256,),
        transport="https-json",
        valid_from=max(0, now - 60),
        valid_until=now + 3600,
        version=1,
    )
    proof = FacilitatorTransportProof(
        facilitator_id=XPAY_FACILITATOR_ID,
        verify_url=client.verify_url,
        settle_url=client.settle_url,
        resolved_host=evidence.resolved_host,
        tls_spki_sha256=evidence.tls_spki_sha256,
        verify_behavior="not-used-local-independent",
        settle_behavior="settlement-only",
        independent_probe=True,
        probe_evidence_digest=evidence.digest,
        observer=evidence.observer,
        observed_at=evidence.observed_at,
        valid_until=now + 600,
    )

    registry = FacilitatorRegistry()
    admission = registry.admit(
        binding,
        proof,
        evidence,
        capability,
        now=now,
    )
    if admission.decision != "ADMIT":
        raise XPayRuntimeError("xpay-facilitator-not-admitted:" + ",".join(admission.reasons))
    return registry, client, XPAY_FACILITATOR_ID
