from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import urlsplit

from src.model import canonical_hash

FACILITATOR_BINDING_SCHEMA = "agentpay-facilitator-binding/1"
FACILITATOR_TRANSPORT_PROBE_SCHEMA = "agentpay-facilitator-transport-probe/1"
FACILITATOR_TRANSPORT_PROOF_SCHEMA = "agentpay-facilitator-transport-proof/2"
FACILITATOR_CAPABILITY_EVIDENCE_SCHEMA = "agentpay-facilitator-capability-evidence/1"
FACILITATOR_ADMISSION_SCHEMA = "agentpay-facilitator-admission/1"


def _clean(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(v).strip().lower() for v in values if str(v).strip()}))


def _required(value: str, code: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(code)
    return value


def _endpoint(value: str, code: str) -> tuple[str, str]:
    value = _required(value, code)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(code)
    return value, parsed.hostname.lower()


@dataclass(frozen=True)
class FacilitatorBinding:
    facilitator_id: str
    legal_identity: str
    verify_url: str
    settle_url: str
    schemes: tuple[str, ...]
    networks: tuple[str, ...]
    asset_contracts: tuple[str, ...]
    dns_names: tuple[str, ...]
    tls_spki_sha256: tuple[str, ...]
    transport: str
    valid_from: int
    valid_until: int
    version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "facilitator_id", _required(self.facilitator_id, "facilitator-id-required"))
        object.__setattr__(self, "legal_identity", _required(self.legal_identity, "facilitator-identity-required"))
        verify_url, verify_host = _endpoint(self.verify_url, "facilitator-verify-url-invalid")
        settle_url, settle_host = _endpoint(self.settle_url, "facilitator-settle-url-invalid")
        if verify_url == settle_url:
            raise ValueError("facilitator-endpoints-not-distinct")
        if verify_host != settle_host:
            raise ValueError("facilitator-endpoint-host-mismatch")
        object.__setattr__(self, "verify_url", verify_url)
        object.__setattr__(self, "settle_url", settle_url)
        object.__setattr__(self, "schemes", _clean(self.schemes))
        object.__setattr__(self, "networks", _clean(self.networks))
        object.__setattr__(self, "asset_contracts", _clean(self.asset_contracts))
        object.__setattr__(self, "dns_names", _clean(self.dns_names))
        object.__setattr__(self, "tls_spki_sha256", _clean(self.tls_spki_sha256))
        object.__setattr__(self, "transport", _required(self.transport, "facilitator-transport-required"))
        if verify_host not in self.dns_names:
            raise ValueError("facilitator-host-not-bound")
        if not self.schemes or not self.networks or not self.asset_contracts:
            raise ValueError("facilitator-payment-scope-empty")
        if not self.tls_spki_sha256:
            raise ValueError("facilitator-tls-pin-required")
        if self.transport != "https-json":
            raise ValueError("facilitator-transport-unsupported")
        if self.valid_from < 0 or self.valid_until <= self.valid_from:
            raise ValueError("facilitator-validity-invalid")
        if self.version <= 0:
            raise ValueError("facilitator-version-invalid")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": FACILITATOR_BINDING_SCHEMA, **asdict(self)})


@dataclass(frozen=True)
class FacilitatorProbeEvidence:
    facilitator_id: str
    verify_url: str
    settle_url: str
    resolved_host: str
    resolved_addresses: tuple[str, ...]
    tls_spki_sha256: str
    tls_cert_sha256: str
    tls_subject: str
    tls_issuer: str
    verify_unauthenticated_status: int
    settle_unauthenticated_status: int
    observer: str
    observed_at: int

    def __post_init__(self) -> None:
        _endpoint(self.verify_url, "facilitator-probe-verify-url-invalid")
        _endpoint(self.settle_url, "facilitator-probe-settle-url-invalid")
        object.__setattr__(self, "resolved_host", _required(self.resolved_host, "facilitator-probe-host-required").lower())
        object.__setattr__(self, "resolved_addresses", _clean(self.resolved_addresses))
        object.__setattr__(self, "tls_spki_sha256", _required(self.tls_spki_sha256, "facilitator-probe-spki-required").lower())
        object.__setattr__(self, "tls_cert_sha256", _required(self.tls_cert_sha256, "facilitator-probe-cert-required").lower())
        object.__setattr__(self, "tls_subject", _required(self.tls_subject, "facilitator-probe-subject-required"))
        object.__setattr__(self, "tls_issuer", _required(self.tls_issuer, "facilitator-probe-issuer-required"))
        object.__setattr__(self, "observer", _required(self.observer, "facilitator-probe-observer-required"))
        if not self.resolved_addresses:
            raise ValueError("facilitator-probe-dns-empty")
        if self.verify_unauthenticated_status not in {400, 401, 403}:
            raise ValueError("facilitator-probe-verify-boundary-unproven")
        if self.settle_unauthenticated_status not in {400, 401, 403}:
            raise ValueError("facilitator-probe-settle-boundary-unproven")
        if self.observed_at < 0:
            raise ValueError("facilitator-probe-time-invalid")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": FACILITATOR_TRANSPORT_PROBE_SCHEMA, **asdict(self)})


@dataclass(frozen=True)
class FacilitatorCapabilityEvidence:
    facilitator_id: str
    supported_url: str
    supported_response_digest: str
    schemes: tuple[str, ...]
    networks: tuple[str, ...]
    authenticated: bool
    observer: str
    observed_at: int
    valid_until: int
    access_model: str = "authenticated"

    def __post_init__(self) -> None:
        _endpoint(self.supported_url, "facilitator-capability-url-invalid")
        object.__setattr__(self, "schemes", _clean(self.schemes))
        object.__setattr__(self, "networks", _clean(self.networks))
        object.__setattr__(self, "supported_response_digest", _required(self.supported_response_digest, "facilitator-capability-response-digest-required"))
        object.__setattr__(self, "observer", _required(self.observer, "facilitator-capability-observer-required"))
        object.__setattr__(self, "access_model", _required(self.access_model, "facilitator-capability-access-model-required").lower())
        if self.access_model not in {"authenticated", "public"}:
            raise ValueError("facilitator-capability-access-model-invalid")
        if self.access_model == "authenticated" and not self.authenticated:
            raise ValueError("facilitator-capability-authentication-required")
        if self.access_model == "public" and self.authenticated:
            raise ValueError("facilitator-capability-public-auth-contradiction")
        if not self.schemes or not self.networks:
            raise ValueError("facilitator-capability-scope-empty")
        if self.observed_at < 0 or self.valid_until <= self.observed_at:
            raise ValueError("facilitator-capability-validity-invalid")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": FACILITATOR_CAPABILITY_EVIDENCE_SCHEMA, **asdict(self)})


@dataclass(frozen=True)
class FacilitatorTransportProof:
    facilitator_id: str
    verify_url: str
    settle_url: str
    resolved_host: str
    tls_spki_sha256: str
    verify_behavior: str
    settle_behavior: str
    independent_probe: bool
    probe_evidence_digest: str
    observer: str
    observed_at: int
    valid_until: int

    def __post_init__(self) -> None:
        _endpoint(self.verify_url, "facilitator-proof-verify-url-invalid")
        _endpoint(self.settle_url, "facilitator-proof-settle-url-invalid")
        object.__setattr__(self, "resolved_host", str(self.resolved_host).strip().lower())
        object.__setattr__(self, "tls_spki_sha256", str(self.tls_spki_sha256).strip().lower())
        if not self.resolved_host or not self.tls_spki_sha256:
            raise ValueError("facilitator-proof-transport-identity-missing")
        object.__setattr__(self, "probe_evidence_digest", _required(self.probe_evidence_digest, "facilitator-proof-evidence-required"))
        object.__setattr__(self, "observer", _required(self.observer, "facilitator-proof-observer-required"))
        if self.observed_at < 0 or self.valid_until <= self.observed_at:
            raise ValueError("facilitator-proof-validity-invalid")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": FACILITATOR_TRANSPORT_PROOF_SCHEMA, **asdict(self)})


@dataclass(frozen=True)
class FacilitatorAdmission:
    facilitator_id: str
    binding_digest: str
    transport_proof_digest: str
    capability_evidence_digest: str
    decision: str
    reasons: tuple[str, ...]
    admitted_at: int
    valid_until: int

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": FACILITATOR_ADMISSION_SCHEMA, **asdict(self)})


def evaluate_facilitator(
    binding: FacilitatorBinding,
    proof: FacilitatorTransportProof,
    evidence: FacilitatorProbeEvidence,
    capability: FacilitatorCapabilityEvidence,
    *,
    now: int,
) -> FacilitatorAdmission:
    reasons: list[str] = []
    host = urlsplit(binding.verify_url).hostname.lower()

    if capability.facilitator_id != binding.facilitator_id:
        reasons.append("facilitator-capability-identity-mismatch")
    expected_supported_url = binding.verify_url.rsplit("/", 1)[0] + "/supported"
    if capability.supported_url != expected_supported_url:
        reasons.append("facilitator-capability-endpoint-mismatch")
    if now > capability.valid_until:
        reasons.append("facilitator-capability-evidence-expired")
    for scheme in binding.schemes:
        if scheme not in capability.schemes:
            reasons.append("facilitator-capability-scheme-unproven")
    for network in binding.networks:
        if network not in capability.networks:
            reasons.append("facilitator-capability-network-unproven")

    if proof.probe_evidence_digest != evidence.digest:
        reasons.append("facilitator-probe-evidence-mismatch")
    if proof.observer != evidence.observer:
        reasons.append("facilitator-probe-observer-mismatch")
    if evidence.facilitator_id != binding.facilitator_id:
        reasons.append("facilitator-probe-identity-mismatch")
    if evidence.verify_url != binding.verify_url or evidence.settle_url != binding.settle_url:
        reasons.append("facilitator-probe-endpoint-mismatch")
    if evidence.resolved_host != host or evidence.resolved_host not in binding.dns_names:
        reasons.append("facilitator-probe-dns-mismatch")
    if evidence.tls_spki_sha256 not in binding.tls_spki_sha256:
        reasons.append("facilitator-probe-tls-pin-mismatch")

    if proof.facilitator_id != binding.facilitator_id:
        reasons.append("facilitator-proof-identity-mismatch")
    if proof.verify_url != binding.verify_url or proof.settle_url != binding.settle_url:
        reasons.append("facilitator-proof-endpoint-mismatch")
    if proof.resolved_host != host or proof.resolved_host not in binding.dns_names:
        reasons.append("facilitator-proof-dns-mismatch")
    if proof.tls_spki_sha256 not in binding.tls_spki_sha256:
        reasons.append("facilitator-proof-tls-pin-mismatch")
    if proof.verify_behavior not in {"verification-only", "not-used-local-independent"}:
        reasons.append("facilitator-verify-behavior-unproven")
    if proof.settle_behavior != "settlement-only":
        reasons.append("facilitator-settle-behavior-unproven")
    if not proof.independent_probe:
        reasons.append("facilitator-independent-probe-required")
    if now < binding.valid_from:
        reasons.append("facilitator-not-yet-valid")
    if now > binding.valid_until:
        reasons.append("facilitator-binding-expired")
    if now > proof.valid_until:
        reasons.append("facilitator-transport-proof-expired")

    return FacilitatorAdmission(
        facilitator_id=binding.facilitator_id,
        binding_digest=binding.digest,
        transport_proof_digest=proof.digest,
        capability_evidence_digest=capability.digest,
        decision="ADMIT" if not reasons else "DENY",
        reasons=tuple(reasons) or ("facilitator-binding-and-transport-satisfy-policy",),
        admitted_at=now,
        valid_until=min(binding.valid_until, proof.valid_until, capability.valid_until),
    )


class FacilitatorRegistry:
    def __init__(self) -> None:
        self._bindings: dict[str, FacilitatorBinding] = {}
        self._proofs: dict[str, FacilitatorTransportProof] = {}
        self._evidence: dict[str, FacilitatorProbeEvidence] = {}
        self._capabilities: dict[str, FacilitatorCapabilityEvidence] = {}
        self._admissions: dict[str, FacilitatorAdmission] = {}

    def admit(
        self,
        binding: FacilitatorBinding,
        proof: FacilitatorTransportProof,
        evidence: FacilitatorProbeEvidence,
        capability: FacilitatorCapabilityEvidence,
        *,
        now: int,
    ) -> FacilitatorAdmission:
        admission = evaluate_facilitator(binding, proof, evidence, capability, now=now)
        if admission.decision != "ADMIT":
            return admission
        current = self._bindings.get(binding.facilitator_id)
        if current is not None and binding.version <= current.version:
            raise ValueError("facilitator-version-not-monotonic")
        self._bindings[binding.facilitator_id] = binding
        self._proofs[binding.facilitator_id] = proof
        self._evidence[binding.facilitator_id] = evidence
        self._capabilities[binding.facilitator_id] = capability
        self._admissions[binding.facilitator_id] = admission
        return admission

    def revoke(self, facilitator_id: str) -> None:
        if facilitator_id not in self._bindings:
            raise ValueError("facilitator-not-admitted")
        self._bindings.pop(facilitator_id, None)
        self._proofs.pop(facilitator_id, None)
        self._evidence.pop(facilitator_id, None)
        self._capabilities.pop(facilitator_id, None)
        self._admissions.pop(facilitator_id, None)

    def require(
        self,
        facilitator_id: str,
        *,
        scheme: str,
        network: str,
        asset_contract: str,
        now: int,
    ) -> tuple[FacilitatorBinding, FacilitatorTransportProof, FacilitatorAdmission]:
        binding = self._bindings.get(facilitator_id)
        proof = self._proofs.get(facilitator_id)
        evidence = self._evidence.get(facilitator_id)
        capability = self._capabilities.get(facilitator_id)
        admission = self._admissions.get(facilitator_id)
        if binding is None or proof is None or evidence is None or capability is None or admission is None or admission.decision != "ADMIT":
            raise ValueError("facilitator-not-admitted")
        if admission.binding_digest != binding.digest or admission.transport_proof_digest != proof.digest:
            raise ValueError("facilitator-admission-binding-mismatch")
        if proof.probe_evidence_digest != evidence.digest:
            raise ValueError("facilitator-probe-evidence-mismatch")
        if admission.capability_evidence_digest != capability.digest:
            raise ValueError("facilitator-capability-evidence-mismatch")
        if now > admission.valid_until:
            raise ValueError("facilitator-admission-expired")
        if scheme.lower() not in binding.schemes:
            raise ValueError("facilitator-scheme-not-admitted")
        if network.lower() not in binding.networks:
            raise ValueError("facilitator-network-not-admitted")
        if asset_contract.lower() not in binding.asset_contracts:
            raise ValueError("facilitator-asset-not-admitted")
        return binding, proof, admission
