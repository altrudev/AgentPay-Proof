from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from src.model import canonical_hash

PROVIDER_BINDING_SCHEMA = "agentpay-provider-binding/1"
PROVIDER_ADMISSION_SCHEMA = "agentpay-provider-admission/1"

REQUIRED_EVIDENCE = (
    "execution_receipt",
    "result_observation",
    "settlement_observation",
)


def _clean(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(v).strip() for v in values if str(v).strip()}))


def _required(value: str, code: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(code)
    return value


def _address(value: str) -> str:
    value = str(value).strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError("provider-payment-recipient-invalid")
    int(value[2:], 16)
    return value


@dataclass(frozen=True)
class ProviderBinding:
    provider_id: str
    legal_identity: str
    capability: str
    adapter_id: str
    request_schema: str
    response_schema: str
    observation_schema: str
    payment_recipient: str
    settlement_asset: str
    allowed_disclosures: tuple[str, ...]
    maximum_retention_seconds: int
    evidence_types: tuple[str, ...]
    idempotency_model: str
    cancellation_model: str
    observation_model: str
    jurisdiction: str
    valid_from: int
    valid_until: int
    version: int

    def __post_init__(self) -> None:
        for field_name, code in (
            ("provider_id", "provider-id-required"),
            ("legal_identity", "provider-identity-required"),
            ("capability", "provider-capability-required"),
            ("adapter_id", "provider-adapter-required"),
            ("request_schema", "provider-request-schema-required"),
            ("response_schema", "provider-response-schema-required"),
            ("observation_schema", "provider-observation-schema-required"),
            ("settlement_asset", "provider-settlement-asset-required"),
            ("idempotency_model", "provider-idempotency-required"),
            ("cancellation_model", "provider-cancellation-required"),
            ("observation_model", "provider-observation-model-required"),
            ("jurisdiction", "provider-jurisdiction-required"),
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), code))

        object.__setattr__(self, "payment_recipient", _address(self.payment_recipient))
        object.__setattr__(self, "settlement_asset", self.settlement_asset.upper())
        object.__setattr__(self, "allowed_disclosures", _clean(self.allowed_disclosures))
        object.__setattr__(self, "evidence_types", _clean(self.evidence_types))

        if self.maximum_retention_seconds < 0:
            raise ValueError("provider-retention-invalid")
        if self.valid_from < 0 or self.valid_until <= self.valid_from:
            raise ValueError("provider-validity-invalid")
        if self.version <= 0:
            raise ValueError("provider-version-invalid")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": PROVIDER_BINDING_SCHEMA, **asdict(self)})


@dataclass(frozen=True)
class ProviderAdmission:
    provider_id: str
    binding_digest: str
    decision: str
    reasons: tuple[str, ...]
    admitted_at: int
    valid_until: int

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": PROVIDER_ADMISSION_SCHEMA, **asdict(self)})


def evaluate_provider_binding(binding: ProviderBinding, *, now: int) -> ProviderAdmission:
    reasons: list[str] = []

    if now < binding.valid_from:
        reasons.append("provider-not-yet-valid")
    if now > binding.valid_until:
        reasons.append("provider-binding-expired")
    if binding.settlement_asset != "USDC":
        reasons.append("provider-settlement-asset-unsupported")
    if binding.maximum_retention_seconds != 0:
        reasons.append("provider-retention-not-zero")

    missing = set(REQUIRED_EVIDENCE) - set(binding.evidence_types)
    if missing:
        reasons.append("provider-evidence-incomplete")

    if binding.idempotency_model not in {
        "idempotency-key-required",
        "single-use-request-id",
    }:
        reasons.append("provider-idempotency-unsupported")
    if binding.cancellation_model not in {
        "cancel-before-dispatch",
        "non-cancellable-after-dispatch",
    }:
        reasons.append("provider-cancellation-unsupported")
    if binding.observation_model not in {
        "independent-fetch",
        "signed-result-plus-independent-fetch",
    }:
        reasons.append("provider-observation-unsupported")

    decision = "ADMIT" if not reasons else "DENY"
    return ProviderAdmission(
        provider_id=binding.provider_id,
        binding_digest=binding.digest,
        decision=decision,
        reasons=tuple(reasons) or ("provider-binding-satisfies-policy",),
        admitted_at=now,
        valid_until=binding.valid_until,
    )


class ProviderRegistry:
    def __init__(self) -> None:
        self._bindings: dict[str, ProviderBinding] = {}
        self._admissions: dict[str, ProviderAdmission] = {}

    def admit(self, binding: ProviderBinding, *, now: int) -> ProviderAdmission:
        admission = evaluate_provider_binding(binding, now=now)
        if admission.decision != "ADMIT":
            return admission
        current = self._bindings.get(binding.provider_id)
        if current is not None and binding.version <= current.version:
            raise ValueError("provider-version-not-monotonic")
        self._bindings[binding.provider_id] = binding
        self._admissions[binding.provider_id] = admission
        return admission

    def require(
        self,
        provider_id: str,
        capability: str,
        *,
        now: int,
    ) -> tuple[ProviderBinding, ProviderAdmission]:
        binding = self._bindings.get(provider_id)
        admission = self._admissions.get(provider_id)
        if binding is None or admission is None:
            raise ValueError("provider-not-admitted")
        if admission.decision != "ADMIT":
            raise ValueError("provider-not-admitted")
        if admission.binding_digest != binding.digest:
            raise ValueError("provider-admission-binding-mismatch")
        if now > min(binding.valid_until, admission.valid_until):
            raise ValueError("provider-admission-expired")
        if binding.capability != capability:
            raise ValueError("provider-capability-binding-mismatch")
        return binding, admission

    def snapshot(self) -> dict:
        return {
            provider_id: {
                "binding": {**asdict(binding), "digest": binding.digest},
                "admission": {
                    **asdict(self._admissions[provider_id]),
                    "digest": self._admissions[provider_id].digest,
                },
            }
            for provider_id, binding in sorted(self._bindings.items())
        }


def reference_provider_binding(
    *,
    payment_recipient: str,
    now: int,
) -> ProviderBinding:
    """Reference-only binding used to test the admission boundary.

    This is deliberately not an external-provider claim. Production paid use
    remains separately gated and should not enable this binding.
    """
    return ProviderBinding(
        provider_id="provider:render-only",
        legal_identity="REFERENCE-ONLY / AgentPay test fixture",
        capability="browser.render.verify",
        adapter_id="reference.browser-render.verify/1",
        request_schema="agentpay-render-verify-request/1",
        response_schema="agentpay-render-verify-result/1",
        observation_schema="agentpay-render-verify-observation/1",
        payment_recipient=payment_recipient,
        settlement_asset="USDC",
        allowed_disclosures=("rendered_page",),
        maximum_retention_seconds=0,
        evidence_types=(
            "execution_receipt",
            "result_observation",
            "settlement_observation",
        ),
        idempotency_model="single-use-request-id",
        cancellation_model="cancel-before-dispatch",
        observation_model="independent-fetch",
        jurisdiction="CA",
        valid_from=now,
        valid_until=now + 3600,
        version=1,
    )


def reference_provider_registry(
    *,
    payment_recipient: str,
    now: int,
) -> ProviderRegistry:
    # Stable test/reference binding: its digest must not change between
    # prepare, confirm and reconcile requests.
    binding = ProviderBinding(
        provider_id="provider:render-only",
        legal_identity="REFERENCE-ONLY / AgentPay test fixture",
        capability="browser.render.verify",
        adapter_id="reference.browser-render.verify/1",
        request_schema="agentpay-render-verify-request/1",
        response_schema="agentpay-render-verify-result/1",
        observation_schema="agentpay-render-verify-observation/1",
        payment_recipient=payment_recipient,
        settlement_asset="USDC",
        allowed_disclosures=("rendered_page",),
        maximum_retention_seconds=0,
        evidence_types=(
            "execution_receipt",
            "result_observation",
            "settlement_observation",
        ),
        idempotency_model="single-use-request-id",
        cancellation_model="cancel-before-dispatch",
        observation_model="independent-fetch",
        jurisdiction="CA",
        valid_from=0,
        valid_until=4_102_444_800,
        version=1,
    )
    if now > binding.valid_until:
        raise RuntimeError("reference-provider-binding-expired")
    registry = ProviderRegistry()
    admission = registry.admit(binding, now=0)
    if admission.decision != "ADMIT":
        raise RuntimeError("reference-provider-binding-not-admitted")
    return registry
