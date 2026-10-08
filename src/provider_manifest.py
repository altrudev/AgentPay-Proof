from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
from typing import Callable, Mapping

from src.model import canonical_hash
from src.provider_admission import ProviderBinding

PROVIDER_MANIFEST_SCHEMA = "agentpay-provider-manifest/1"
PROVIDER_EVIDENCE_SCHEMA = "agentpay-provider-evidence/1"

SignatureVerifier = Callable[[str, str, str], bool]
EvidenceVerifier = Callable[["ProviderEvidence", "ProviderManifest"], bool]


def _required(value: str, code: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(code)
    return value


@dataclass(frozen=True)
class ProviderEvidence:
    evidence_type: str
    subject: str
    issuer: str
    reference: str
    observed_at: int
    expires_at: int
    digest: str
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, code in (
            ("evidence_type", "provider-evidence-type-required"),
            ("subject", "provider-evidence-subject-required"),
            ("issuer", "provider-evidence-issuer-required"),
            ("reference", "provider-evidence-reference-required"),
            ("digest", "provider-evidence-digest-required"),
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), code))
        if self.observed_at < 0 or self.expires_at <= self.observed_at:
            raise ValueError("provider-evidence-validity-invalid")
        if not isinstance(self.details, dict):
            raise ValueError("provider-evidence-details-invalid")

    @property
    def proof_digest(self) -> str:
        return canonical_hash({"schema": PROVIDER_EVIDENCE_SCHEMA, **asdict(self)})


@dataclass(frozen=True)
class ProviderManifest:
    manifest_id: str
    provider_id: str
    binding: ProviderBinding
    issuer_key_id: str
    signature: str
    evidence: tuple[ProviderEvidence, ...]
    issued_at: int
    expires_at: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_id", _required(self.manifest_id, "provider-manifest-id-required"))
        object.__setattr__(self, "provider_id", _required(self.provider_id, "provider-manifest-provider-required"))
        object.__setattr__(self, "issuer_key_id", _required(self.issuer_key_id, "provider-manifest-key-required"))
        object.__setattr__(self, "signature", _required(self.signature, "provider-manifest-signature-required"))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.provider_id != self.binding.provider_id:
            raise ValueError("provider-manifest-binding-provider-mismatch")
        if self.issued_at < 0 or self.expires_at <= self.issued_at:
            raise ValueError("provider-manifest-validity-invalid")
        if self.expires_at > self.binding.valid_until:
            raise ValueError("provider-manifest-outlives-binding")

    @property
    def unsigned_document(self) -> dict:
        return {
            "schema": PROVIDER_MANIFEST_SCHEMA,
            "manifest_id": self.manifest_id,
            "provider_id": self.provider_id,
            "binding": asdict(self.binding),
            "issuer_key_id": self.issuer_key_id,
            "evidence": [asdict(item) for item in self.evidence],
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @property
    def digest(self) -> str:
        return canonical_hash(self.unsigned_document)


@dataclass(frozen=True)
class ProviderManifestVerification:
    verdict: str
    reasons: tuple[str, ...]
    manifest_digest: str
    binding_digest: str
    evidence_digests: tuple[str, ...]

    @property
    def digest(self) -> str:
        return canonical_hash(asdict(self))


REQUIRED_PROVIDER_EVIDENCE = ("identity-control", "recipient-control", "endpoint-control")


def ed25519_verify(public_key_b64: str, message_digest: str, signature_b64: str) -> bool:
    """Verify a detached Ed25519 signature over the ASCII manifest digest.

    cryptography is intentionally imported inside the verifier. A deployment
    without the dependency does not silently downgrade; the verifier raises and
    verify_provider_manifest returns NOT VERIFIED.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
    signature = base64.b64decode(signature_b64, validate=True)
    public_key.verify(signature, message_digest.encode("ascii"))
    return True


def provider_manifest_from_document(document: Mapping[str, object]) -> ProviderManifest:
    try:
        raw_binding = document["binding"]
        raw_evidence = document["evidence"]
        if not isinstance(raw_binding, Mapping) or not isinstance(raw_evidence, list):
            raise TypeError
        binding = ProviderBinding(**dict(raw_binding))
        evidence = tuple(
            ProviderEvidence(**dict(item))
            for item in raw_evidence
            if isinstance(item, Mapping)
        )
        if len(evidence) != len(raw_evidence):
            raise TypeError
        return ProviderManifest(
            manifest_id=str(document["manifest_id"]),
            provider_id=str(document["provider_id"]),
            binding=binding,
            issuer_key_id=str(document["issuer_key_id"]),
            signature=str(document["signature"]),
            evidence=evidence,
            issued_at=int(document["issued_at"]),
            expires_at=int(document["expires_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("provider-manifest-document-invalid") from exc


def verify_provider_manifest(
    manifest: ProviderManifest,
    *,
    now: int,
    signature_verifier: SignatureVerifier | None,
    trusted_issuers: Mapping[str, str],
    evidence_verifiers: Mapping[str, EvidenceVerifier] | None = None,
) -> ProviderManifestVerification:
    reasons: list[str] = []
    if now < manifest.issued_at:
        reasons.append("provider-manifest-not-yet-valid")
    if now > manifest.expires_at:
        reasons.append("provider-manifest-expired")
    if now < manifest.binding.valid_from or now > manifest.binding.valid_until:
        reasons.append("provider-binding-outside-validity")

    public_identity = trusted_issuers.get(manifest.issuer_key_id)
    if public_identity is None:
        reasons.append("provider-manifest-issuer-untrusted")
    elif signature_verifier is None:
        reasons.append("provider-signature-verifier-unavailable")
    else:
        try:
            valid_signature = bool(signature_verifier(public_identity, manifest.digest, manifest.signature))
        except Exception:
            valid_signature = False
        if not valid_signature:
            reasons.append("provider-manifest-signature-invalid")

    by_type: dict[str, ProviderEvidence] = {}
    evidence_verifiers = evidence_verifiers or {}
    for item in manifest.evidence:
        if item.evidence_type in by_type:
            reasons.append("provider-evidence-duplicate-type")
            continue
        by_type[item.evidence_type] = item
        if item.subject != manifest.provider_id:
            reasons.append("provider-evidence-subject-mismatch")
        if now > item.expires_at:
            reasons.append("provider-evidence-expired")
        if item.observed_at > now:
            reasons.append("provider-evidence-from-future")
        verifier = evidence_verifiers.get(item.evidence_type)
        if verifier is None:
            reasons.append(f"provider-evidence-verifier-unavailable:{item.evidence_type}")
        else:
            try:
                verified = bool(verifier(item, manifest))
            except Exception:
                verified = False
            if not verified:
                reasons.append(f"provider-evidence-verification-failed:{item.evidence_type}")

    for required in REQUIRED_PROVIDER_EVIDENCE:
        if required not in by_type:
            reasons.append(f"provider-evidence-missing:{required}")

    recipient = by_type.get("recipient-control")
    if recipient is not None and recipient.reference.lower() != manifest.binding.payment_recipient.lower():
        reasons.append("provider-recipient-evidence-mismatch")

    endpoint = by_type.get("endpoint-control")
    if endpoint is not None and manifest.binding.adapter_id not in endpoint.reference:
        reasons.append("provider-endpoint-evidence-mismatch")

    return ProviderManifestVerification(
        verdict="VERIFIED" if not reasons else "NOT VERIFIED",
        reasons=tuple(sorted(set(reasons))) or ("provider-manifest-verified",),
        manifest_digest=manifest.digest,
        binding_digest=manifest.binding.digest,
        evidence_digests=tuple(sorted(item.proof_digest for item in manifest.evidence)),
    )
