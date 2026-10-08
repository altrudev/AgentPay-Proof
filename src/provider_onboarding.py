from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Callable

from src.model import canonical_hash
from src.provider_admission import ProviderBinding
from src.provider_endpoint_probe import (
    endpoint_control_evidence,
    identity_control_evidence,
    probe_provider_endpoint,
)
from src.provider_evidence_verifiers import PROVIDER_EVIDENCE_VERIFIERS
from src.provider_manifest import (
    ProviderManifest,
    ed25519_verify,
    verify_provider_manifest,
)
from src.provider_manifest_signing import (
    load_ed25519_private_key,
    public_key_b64,
    sign_provider_manifest,
)
from src.provider_profile import (
    AGENTPAY_PROVIDER_ADAPTER_URL,
    AGENTPAY_PROVIDER_BASE_URL,
    AGENTPAY_PROVIDER_CAPABILITY,
    AGENTPAY_PROVIDER_DOMAIN,
    AGENTPAY_PROVIDER_ID,
    AGENTPAY_PROVIDER_KEY_ID,
    AGENTPAY_PROVIDER_LEGAL_IDENTITY,
    AGENTPAY_PROVIDER_PUBLIC_KEY_B64,
    AGENTPAY_PROVIDER_RECIPIENT,
    AGENTPAY_PROVIDER_SERVICE_ID,
    public_provider_identity,
)
from src.provider_recipient_proof import (
    RecipientControlChallenge,
    new_recipient_challenge,
    recipient_provider_evidence,
    verify_recipient_signature,
)


class ProviderOnboardingError(RuntimeError):
    pass


def provider_profile_digest() -> str:
    identity = public_provider_identity()
    return str(identity["digest"])


def create_provider_recipient_challenge(
    *,
    now: int,
    ttl_seconds: int = 600,
    nonce: str | None = None,
) -> RecipientControlChallenge:
    return new_recipient_challenge(
        provider_id=AGENTPAY_PROVIDER_ID,
        recipient=AGENTPAY_PROVIDER_RECIPIENT,
        chain_id=8453,
        domain=AGENTPAY_PROVIDER_DOMAIN,
        endpoint=AGENTPAY_PROVIDER_ADAPTER_URL,
        quote_digest=provider_profile_digest(),
        now=now,
        ttl_seconds=ttl_seconds,
        nonce=nonce,
    )


def provider_binding(*, now: int, version: int, lifetime_seconds: int = 86_400) -> ProviderBinding:
    if lifetime_seconds <= 0 or lifetime_seconds > 7 * 86_400:
        raise ProviderOnboardingError("provider-binding-lifetime-outside-policy")
    return ProviderBinding(
        provider_id=AGENTPAY_PROVIDER_ID,
        legal_identity=AGENTPAY_PROVIDER_LEGAL_IDENTITY,
        capability=AGENTPAY_PROVIDER_CAPABILITY,
        adapter_id=AGENTPAY_PROVIDER_ADAPTER_URL,
        request_schema="agentpay-code-analysis-request/1",
        response_schema="agentpay-code-analysis-result/1",
        observation_schema="agentpay-code-analysis-observation/1",
        payment_recipient=AGENTPAY_PROVIDER_RECIPIENT,
        settlement_asset="USDC",
        allowed_disclosures=("document",),
        maximum_retention_seconds=0,
        evidence_types=(
            "execution_receipt",
            "result_observation",
            "settlement_observation",
        ),
        idempotency_model="single-use-request-id",
        cancellation_model="non-cancellable-after-dispatch",
        observation_model="signed-result-plus-independent-fetch",
        jurisdiction="CA",
        valid_from=max(0, now - 60),
        valid_until=now + lifetime_seconds,
        version=version,
    )


def build_signed_provider_manifest(
    *,
    recipient_signature: str,
    challenge: RecipientControlChallenge,
    now: int,
    version: int,
    signing_key_path: str | Path,
    observer: str,
    recover_address: Callable[[str, str], str] | None = None,
    evidence_lifetime_seconds: int = 3600,
    binding_lifetime_seconds: int = 86_400,
) -> ProviderManifest:
    if challenge.provider_id != AGENTPAY_PROVIDER_ID:
        raise ProviderOnboardingError("provider-challenge-provider-mismatch")
    if challenge.recipient != AGENTPAY_PROVIDER_RECIPIENT:
        raise ProviderOnboardingError("provider-challenge-recipient-mismatch")
    if challenge.domain != AGENTPAY_PROVIDER_DOMAIN:
        raise ProviderOnboardingError("provider-challenge-domain-mismatch")
    if challenge.endpoint != AGENTPAY_PROVIDER_ADAPTER_URL:
        raise ProviderOnboardingError("provider-challenge-endpoint-mismatch")
    if challenge.quote_digest != provider_profile_digest():
        raise ProviderOnboardingError("provider-challenge-profile-mismatch")
    if evidence_lifetime_seconds <= 0 or evidence_lifetime_seconds > 24 * 3600:
        raise ProviderOnboardingError("provider-evidence-lifetime-outside-policy")

    observation = probe_provider_endpoint(
        provider_id=AGENTPAY_PROVIDER_ID,
        base_url=AGENTPAY_PROVIDER_BASE_URL,
        service_id=AGENTPAY_PROVIDER_SERVICE_ID,
        observer=observer,
        observed_at=now,
    )
    if recover_address is None:
        recipient_proof = verify_recipient_signature(
            challenge, signature=recipient_signature, now=now
        )
    else:
        recipient_proof = verify_recipient_signature(
            challenge,
            signature=recipient_signature,
            now=now,
            recover_address=recover_address,
        )
    evidence_expires = now + evidence_lifetime_seconds
    evidence = (
        identity_control_evidence(observation, expires_at=evidence_expires),
        endpoint_control_evidence(
            observation,
            adapter_id=AGENTPAY_PROVIDER_ADAPTER_URL,
            expires_at=evidence_expires,
        ),
        recipient_provider_evidence(
            challenge,
            recipient_proof,
            issuer=observer,
            expires_at=evidence_expires,
        ),
    )
    binding = provider_binding(
        now=now, version=version, lifetime_seconds=binding_lifetime_seconds
    )
    manifest_expires = min(binding.valid_until, evidence_expires)
    unsigned = ProviderManifest(
        manifest_id="provider-manifest:" + canonical_hash(
            {
                "provider": AGENTPAY_PROVIDER_ID,
                "binding": binding.digest,
                "evidence": [item.proof_digest for item in evidence],
                "issued_at": now,
            }
        )[:32],
        provider_id=AGENTPAY_PROVIDER_ID,
        binding=binding,
        issuer_key_id=AGENTPAY_PROVIDER_KEY_ID,
        signature="UNSIGNED",
        evidence=evidence,
        issued_at=now,
        expires_at=manifest_expires,
    )
    key = load_ed25519_private_key(signing_key_path)
    if public_key_b64(key) != AGENTPAY_PROVIDER_PUBLIC_KEY_B64:
        raise ProviderOnboardingError("provider-signing-key-public-mismatch")
    manifest = sign_provider_manifest(unsigned, private_key=key)
    verification = verify_provider_manifest(
        manifest,
        now=now,
        signature_verifier=ed25519_verify,
        trusted_issuers={AGENTPAY_PROVIDER_KEY_ID: AGENTPAY_PROVIDER_PUBLIC_KEY_B64},
        evidence_verifiers=PROVIDER_EVIDENCE_VERIFIERS,
    )
    if verification.verdict != "VERIFIED":
        raise ProviderOnboardingError(
            "provider-manifest-self-verification-failed:"
            + ",".join(verification.reasons)
        )
    return manifest


def manifest_document(manifest: ProviderManifest) -> dict:
    return {
        "manifest_id": manifest.manifest_id,
        "provider_id": manifest.provider_id,
        "binding": asdict(manifest.binding),
        "issuer_key_id": manifest.issuer_key_id,
        "signature": manifest.signature,
        "evidence": [asdict(item) for item in manifest.evidence],
        "issued_at": manifest.issued_at,
        "expires_at": manifest.expires_at,
        "manifest_digest": manifest.digest,
    }


def write_manifest(manifest: ProviderManifest, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest_document(manifest), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
