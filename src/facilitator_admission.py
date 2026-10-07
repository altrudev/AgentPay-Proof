from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import urlsplit

from src.model import canonical_hash

FACILITATOR_BINDING_SCHEMA = "agentpay-facilitator-binding/1"
FACILITATOR_TRANSPORT_PROOF_SCHEMA = "agentpay-facilitator-transport-proof/1"
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
class FacilitatorTransportProof:
    facilitator_id: str
    verify_url: str
    settle_url: str
    resolved_host: str
    tls_spki_sha256: str
    verify_behavior: str
    settle_behavior: str
    independent_probe: bool
    observed_at: int
    valid_until: int

    def __post_init__(self) -> None:
        _endpoint(self.verify_url, "facilitator-proof-verify-url-invalid")
        _endpoint(self.settle_url, "facilitator-proof-settle-url-invalid")
        object.__setattr__(self, "resolved_host", str(self.resolved_host).strip().lower())
        object.__setattr__(self, "tls_spki_sha256", str(self.tls_spki_sha256).strip().lower())
        if not self.resolved_host or not self.tls_spki_sha256:
            raise ValueError("facilitator-proof-transport-identity-missing")
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
    *,
    now: int,
) -> FacilitatorAdmission:
    reasons: list[str] = []
    host = urlsplit(binding.verify_url).hostname.lower()

    if proof.facilitator_id != binding.facilitator_id:
        reasons.append("facilitator-proof-identity-mismatch")
    if proof.verify_url != binding.verify_url or proof.settle_url != binding.settle_url:
        reasons.append("facilitator-proof-endpoint-mismatch")
    if proof.resolved_host != host or proof.resolved_host not in binding.dns_names:
        reasons.append("facilitator-proof-dns-mismatch")
    if proof.tls_spki_sha256 not in binding.tls_spki_sha256:
        reasons.append("facilitator-proof-tls-pin-mismatch")
    if proof.verify_behavior != "verification-only":
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
        decision="ADMIT" if not reasons else "DENY",
        reasons=tuple(reasons) or ("facilitator-binding-and-transport-satisfy-policy",),
        admitted_at=now,
        valid_until=min(binding.valid_until, proof.valid_until),
    )


class FacilitatorRegistry:
    def __init__(self) -> None:
        self._bindings: dict[str, FacilitatorBinding] = {}
        self._proofs: dict[str, FacilitatorTransportProof] = {}
        self._admissions: dict[str, FacilitatorAdmission] = {}

    def admit(
        self,
        binding: FacilitatorBinding,
        proof: FacilitatorTransportProof,
        *,
        now: int,
    ) -> FacilitatorAdmission:
        admission = evaluate_facilitator(binding, proof, now=now)
        if admission.decision != "ADMIT":
            return admission
        current = self._bindings.get(binding.facilitator_id)
        if current is not None and binding.version <= current.version:
            raise ValueError("facilitator-version-not-monotonic")
        self._bindings[binding.facilitator_id] = binding
        self._proofs[binding.facilitator_id] = proof
        self._admissions[binding.facilitator_id] = admission
        return admission

    def revoke(self, facilitator_id: str) -> None:
        if facilitator_id not in self._bindings:
            raise ValueError("facilitator-not-admitted")
        self._bindings.pop(facilitator_id, None)
        self._proofs.pop(facilitator_id, None)
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
        admission = self._admissions.get(facilitator_id)
        if binding is None or proof is None or admission is None or admission.decision != "ADMIT":
            raise ValueError("facilitator-not-admitted")
        if admission.binding_digest != binding.digest or admission.transport_proof_digest != proof.digest:
            raise ValueError("facilitator-admission-binding-mismatch")
        if now > admission.valid_until:
            raise ValueError("facilitator-admission-expired")
        if scheme.lower() not in binding.schemes:
            raise ValueError("facilitator-scheme-not-admitted")
        if network.lower() not in binding.networks:
            raise ValueError("facilitator-network-not-admitted")
        if asset_contract.lower() not in binding.asset_contracts:
            raise ValueError("facilitator-asset-not-admitted")
        return binding, proof, admission
