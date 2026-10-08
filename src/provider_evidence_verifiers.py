from __future__ import annotations

from src.provider_endpoint_probe import (
    ProviderEndpointObservation,
    endpoint_control_evidence,
    identity_control_evidence,
)
from src.provider_manifest import ProviderEvidence, ProviderManifest
from src.provider_recipient_proof import (
    RecipientControlChallenge,
    RecipientControlProof,
    verify_recipient_signature,
)


def verify_identity_control(evidence: ProviderEvidence, manifest: ProviderManifest) -> bool:
    try:
        raw = evidence.details["observation"]
        observation = ProviderEndpointObservation(**raw)
        expected = identity_control_evidence(observation, expires_at=evidence.expires_at)
    except Exception:
        return False
    identity = observation.identity_document
    return bool(
        evidence.evidence_type == "identity-control"
        and evidence.subject == manifest.provider_id
        and observation.provider_id == manifest.provider_id
        and observation.observed_at == evidence.observed_at
        and evidence.digest == expected.digest
        and evidence.reference == expected.reference
        and identity.get("provider_id") == manifest.provider_id
        and identity.get("issuer_key_id") == manifest.issuer_key_id
        and identity.get("adapter_url") == manifest.binding.adapter_id
        and identity.get("payment_recipient", "").lower()
        == manifest.binding.payment_recipient.lower()
    )


def verify_endpoint_control(evidence: ProviderEvidence, manifest: ProviderManifest) -> bool:
    try:
        raw = evidence.details["observation"]
        observation = ProviderEndpointObservation(**raw)
        expected = endpoint_control_evidence(
            observation,
            adapter_id=manifest.binding.adapter_id,
            expires_at=evidence.expires_at,
        )
    except Exception:
        return False
    return bool(
        evidence.evidence_type == "endpoint-control"
        and evidence.subject == manifest.provider_id
        and observation.provider_id == manifest.provider_id
        and observation.observed_at == evidence.observed_at
        and evidence.digest == expected.digest
        and evidence.reference == manifest.binding.adapter_id
        and evidence.reference == manifest.binding.adapter_id
    )


def verify_recipient_control(evidence: ProviderEvidence, manifest: ProviderManifest) -> bool:
    try:
        challenge = RecipientControlChallenge(**evidence.details["challenge"])
        stored_proof = RecipientControlProof(**evidence.details["proof"])
        verified = verify_recipient_signature(
            challenge,
            signature=stored_proof.signature,
            now=stored_proof.verified_at,
        )
    except Exception:
        return False
    return bool(
        evidence.evidence_type == "recipient-control"
        and evidence.subject == manifest.provider_id
        and challenge.provider_id == manifest.provider_id
        and evidence.reference.lower() == manifest.binding.payment_recipient.lower()
        and challenge.recipient == manifest.binding.payment_recipient.lower()
        and stored_proof.digest == evidence.digest
        and verified.digest == stored_proof.digest
        and verified.recovered_address == manifest.binding.payment_recipient.lower()
    )


PROVIDER_EVIDENCE_VERIFIERS = {
    "identity-control": verify_identity_control,
    "endpoint-control": verify_endpoint_control,
    "recipient-control": verify_recipient_control,
}
