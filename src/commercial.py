from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

from src.model import canonical_hash

COMMERCIAL_SCHEMA = "agentpay-commercial-intent/1"
OFFER_SCHEMA = "agentpay-capability-offer/1"
PLAN_SCHEMA = "agentpay-commercial-plan/1"
PROOF_SCHEMA = "agentpay-commercial-proof/1"

PREFERENCE_KEYS = (
    "disclosure",
    "price",
    "retention",
    "compute",
    "latency",
    "confidence",
)


def _clean_tuple(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(v).strip() for v in values if str(v).strip()}))


def _require_nonempty(value: str, code: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(code)
    return value


@dataclass(frozen=True)
class CommercialIntentCapsule:
    capsule_id: str
    principal_id: str
    purpose: str
    outcome: str
    maximum_spend_atomic: int
    settlement_asset: str
    allowed_capabilities: tuple[str, ...]
    allowed_disclosures: tuple[str, ...]
    prohibited_disclosures: tuple[str, ...]
    minimum_evidence: tuple[str, ...]
    minimum_confidence_bps: int
    maximum_credential_ttl_seconds: int
    maximum_compute_units: int
    maximum_retention_seconds: int
    expires_at: int
    created_at: int
    allowed_providers: tuple[str, ...] = ()
    allowed_jurisdictions: tuple[str, ...] = ()
    preference_order: tuple[str, ...] = (
        "disclosure",
        "price",
        "retention",
        "compute",
        "latency",
        "confidence",
    )
    automatic_execution: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "capsule_id", _require_nonempty(self.capsule_id, "capsule-id-required"))
        object.__setattr__(self, "principal_id", _require_nonempty(self.principal_id, "principal-id-required"))
        object.__setattr__(self, "purpose", _require_nonempty(self.purpose, "purpose-required"))
        object.__setattr__(self, "outcome", _require_nonempty(self.outcome, "outcome-required"))
        object.__setattr__(self, "settlement_asset", _require_nonempty(self.settlement_asset, "asset-required").upper())
        for field_name in (
            "allowed_capabilities",
            "allowed_disclosures",
            "prohibited_disclosures",
            "minimum_evidence",
            "allowed_providers",
            "allowed_jurisdictions",
        ):
            object.__setattr__(self, field_name, _clean_tuple(getattr(self, field_name)))

        preference = tuple(self.preference_order)
        if set(preference) != set(PREFERENCE_KEYS) or len(preference) != len(PREFERENCE_KEYS):
            raise ValueError("preference-order-invalid")
        object.__setattr__(self, "preference_order", preference)

        if self.maximum_spend_atomic < 0:
            raise ValueError("maximum-spend-invalid")
        if not 0 <= self.minimum_confidence_bps <= 10_000:
            raise ValueError("minimum-confidence-invalid")
        if self.maximum_credential_ttl_seconds < 0:
            raise ValueError("credential-ttl-invalid")
        if self.maximum_compute_units < 0:
            raise ValueError("compute-limit-invalid")
        if self.maximum_retention_seconds < 0:
            raise ValueError("retention-limit-invalid")
        if self.expires_at <= self.created_at:
            raise ValueError("capsule-expiry-invalid")
        if set(self.allowed_disclosures) & set(self.prohibited_disclosures):
            raise ValueError("disclosure-policy-conflict")
        if not self.allowed_capabilities:
            raise ValueError("capability-required")
        if not self.minimum_evidence:
            raise ValueError("evidence-required")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": COMMERCIAL_SCHEMA, **asdict(self)})


@dataclass(frozen=True)
class CapabilityOffer:
    offer_id: str
    provider_id: str
    capability: str
    price_atomic: int
    settlement_asset: str
    required_disclosures: tuple[str, ...]
    evidence: tuple[str, ...]
    expected_confidence_bps: int
    credential_ttl_seconds: int
    compute_units: int
    retention_seconds: int
    latency_ms: int
    jurisdiction: str
    expires_at: int

    def __post_init__(self) -> None:
        for field_name, code in (
            ("offer_id", "offer-id-required"),
            ("provider_id", "provider-id-required"),
            ("capability", "offer-capability-required"),
            ("settlement_asset", "offer-asset-required"),
            ("jurisdiction", "offer-jurisdiction-required"),
        ):
            value = _require_nonempty(getattr(self, field_name), code)
            if field_name == "settlement_asset":
                value = value.upper()
            object.__setattr__(self, field_name, value)

        object.__setattr__(self, "required_disclosures", _clean_tuple(self.required_disclosures))
        object.__setattr__(self, "evidence", _clean_tuple(self.evidence))

        if self.price_atomic < 0:
            raise ValueError("offer-price-invalid")
        if not 0 <= self.expected_confidence_bps <= 10_000:
            raise ValueError("offer-confidence-invalid")
        for value, code in (
            (self.credential_ttl_seconds, "offer-credential-ttl-invalid"),
            (self.compute_units, "offer-compute-invalid"),
            (self.retention_seconds, "offer-retention-invalid"),
            (self.latency_ms, "offer-latency-invalid"),
            (self.expires_at, "offer-expiry-invalid"),
        ):
            if value < 0:
                raise ValueError(code)

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": OFFER_SCHEMA, **asdict(self)})


@dataclass(frozen=True)
class OfferEvaluation:
    offer_id: str
    decision: str
    reasons: tuple[str, ...]
    disclosure_count: int

    @property
    def digest(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class CommercialPlan:
    capsule_digest: str
    selected_offer_digest: str | None
    selected_offer_id: str | None
    permitted_offer_ids: tuple[str, ...]
    rejected: tuple[OfferEvaluation, ...]
    frontier_offer_ids: tuple[str, ...]
    requires_human_approval: bool
    reason: str

    @property
    def digest(self) -> str:
        return canonical_hash({
            "schema": PLAN_SCHEMA,
            "capsule_digest": self.capsule_digest,
            "selected_offer_digest": self.selected_offer_digest,
            "selected_offer_id": self.selected_offer_id,
            "permitted_offer_ids": self.permitted_offer_ids,
            "rejected": [asdict(item) for item in self.rejected],
            "frontier_offer_ids": self.frontier_offer_ids,
            "requires_human_approval": self.requires_human_approval,
            "reason": self.reason,
        })


def evaluate_offer(capsule: CommercialIntentCapsule, offer: CapabilityOffer, *, now: int) -> OfferEvaluation:
    reasons: list[str] = []

    if now > capsule.expires_at:
        reasons.append("capsule-expired")
    if now > offer.expires_at:
        reasons.append("offer-expired")
    if offer.capability not in capsule.allowed_capabilities:
        reasons.append("capability-not-authorized")
    if offer.settlement_asset != capsule.settlement_asset:
        reasons.append("settlement-asset-mismatch")
    if offer.price_atomic > capsule.maximum_spend_atomic:
        reasons.append("price-exceeds-authority")

    required = set(offer.required_disclosures)
    allowed = set(capsule.allowed_disclosures)
    prohibited = set(capsule.prohibited_disclosures)
    if required - allowed:
        reasons.append("disclosure-not-authorized")
    if required & prohibited:
        reasons.append("prohibited-disclosure-required")

    if offer.credential_ttl_seconds > capsule.maximum_credential_ttl_seconds:
        reasons.append("credential-ttl-exceeds-authority")
    if offer.compute_units > capsule.maximum_compute_units:
        reasons.append("compute-exceeds-authority")
    if offer.retention_seconds > capsule.maximum_retention_seconds:
        reasons.append("retention-exceeds-authority")
    if offer.expected_confidence_bps < capsule.minimum_confidence_bps:
        reasons.append("confidence-below-target")

    missing_evidence = set(capsule.minimum_evidence) - set(offer.evidence)
    if missing_evidence:
        reasons.append("required-evidence-missing")

    if capsule.allowed_providers and offer.provider_id not in capsule.allowed_providers:
        reasons.append("provider-not-authorized")
    if capsule.allowed_jurisdictions and offer.jurisdiction not in capsule.allowed_jurisdictions:
        reasons.append("jurisdiction-not-authorized")

    return OfferEvaluation(
        offer_id=offer.offer_id,
        decision="DENY" if reasons else "PERMIT",
        reasons=tuple(reasons) or ("within-commercial-envelope",),
        disclosure_count=len(required),
    )


def _dominates(a: CapabilityOffer, b: CapabilityOffer) -> bool:
    """Return True when a is no worse on every planning dimension and better on at least one."""
    a_dims = (
        a.price_atomic,
        len(a.required_disclosures),
        a.retention_seconds,
        a.compute_units,
        a.latency_ms,
        -a.expected_confidence_bps,
    )
    b_dims = (
        b.price_atomic,
        len(b.required_disclosures),
        b.retention_seconds,
        b.compute_units,
        b.latency_ms,
        -b.expected_confidence_bps,
    )
    no_worse = all(x <= y for x, y in zip(a_dims, b_dims))
    strictly_better = any(x < y for x, y in zip(a_dims, b_dims))
    return no_worse and strictly_better


def pareto_frontier(offers: Sequence[CapabilityOffer]) -> tuple[CapabilityOffer, ...]:
    unique = {offer.offer_id: offer for offer in offers}
    values = tuple(unique[key] for key in sorted(unique))
    frontier = [
        candidate
        for candidate in values
        if not any(_dominates(other, candidate) for other in values if other.offer_id != candidate.offer_id)
    ]
    return tuple(sorted(frontier, key=lambda x: x.offer_id))


def _preference_value(offer: CapabilityOffer, key: str) -> int:
    if key == "disclosure":
        return len(offer.required_disclosures)
    if key == "price":
        return offer.price_atomic
    if key == "retention":
        return offer.retention_seconds
    if key == "compute":
        return offer.compute_units
    if key == "latency":
        return offer.latency_ms
    if key == "confidence":
        return -offer.expected_confidence_bps
    raise ValueError("unknown-preference")


def plan_commercial_action(
    capsule: CommercialIntentCapsule,
    offers: Sequence[CapabilityOffer],
    *,
    now: int,
) -> CommercialPlan:
    if not offers:
        return CommercialPlan(
            capsule.digest, None, None, (), (), (), True, "no-offers"
        )

    evaluations = tuple(evaluate_offer(capsule, offer, now=now) for offer in offers)
    by_id = {offer.offer_id: offer for offer in offers}
    permitted = tuple(
        by_id[item.offer_id]
        for item in evaluations
        if item.decision == "PERMIT"
    )
    rejected = tuple(item for item in evaluations if item.decision == "DENY")

    if not permitted:
        return CommercialPlan(
            capsule.digest,
            None,
            None,
            (),
            rejected,
            (),
            True,
            "no-permitted-offer",
        )

    frontier = pareto_frontier(permitted)
    selected = min(
        frontier,
        key=lambda offer: tuple(
            _preference_value(offer, key) for key in capsule.preference_order
        ) + (offer.provider_id, offer.offer_id),
    )

    return CommercialPlan(
        capsule_digest=capsule.digest,
        selected_offer_digest=selected.digest,
        selected_offer_id=selected.offer_id,
        permitted_offer_ids=tuple(sorted(offer.offer_id for offer in permitted)),
        rejected=rejected,
        frontier_offer_ids=tuple(offer.offer_id for offer in frontier),
        requires_human_approval=not capsule.automatic_execution,
        reason="selected-smallest-justified-action",
    )


def plan_explanation(
    capsule: CommercialIntentCapsule,
    offers: Sequence[CapabilityOffer],
    plan: CommercialPlan,
) -> dict:
    by_id = {offer.offer_id: offer for offer in offers}
    selected = by_id.get(plan.selected_offer_id or "")
    rejected = [
        {
            "offer_id": item.offer_id,
            "reasons": list(item.reasons),
        }
        for item in plan.rejected
    ]
    return {
        "purpose": capsule.purpose,
        "outcome": capsule.outcome,
        "selected": (
            {
                "offer_id": selected.offer_id,
                "provider_id": selected.provider_id,
                "capability": selected.capability,
                "price_atomic": selected.price_atomic,
                "settlement_asset": selected.settlement_asset,
                "disclosures": list(selected.required_disclosures),
                "retention_seconds": selected.retention_seconds,
                "credential_ttl_seconds": selected.credential_ttl_seconds,
                "compute_units": selected.compute_units,
                "latency_ms": selected.latency_ms,
                "expected_confidence_bps": selected.expected_confidence_bps,
                "evidence": list(selected.evidence),
            }
            if selected
            else None
        ),
        "frontier_offer_ids": list(plan.frontier_offer_ids),
        "rejected": rejected,
        "requires_human_approval": plan.requires_human_approval,
        "reason": plan.reason,
        "plan_digest": plan.digest,
    }


def make_commercial_proof(
    capsule: CommercialIntentCapsule,
    plan: CommercialPlan,
    *,
    authority_digest: str,
    action_proof_hash: str,
    outcome: str,
    observed_at: int,
) -> dict:
    if plan.selected_offer_id is None or plan.selected_offer_digest is None:
        raise ValueError("commercial-proof-requires-selected-offer")
    authority_digest = _require_nonempty(authority_digest, "authority-digest-required")
    action_proof_hash = _require_nonempty(action_proof_hash, "action-proof-required")
    outcome = _require_nonempty(outcome, "outcome-required")
    if observed_at < capsule.created_at:
        raise ValueError("commercial-proof-time-invalid")

    body = {
        "schema": PROOF_SCHEMA,
        "capsule_digest": capsule.digest,
        "plan_digest": plan.digest,
        "selected_offer_id": plan.selected_offer_id,
        "selected_offer_digest": plan.selected_offer_digest,
        "authority_digest": authority_digest,
        "action_proof_hash": action_proof_hash,
        "outcome": outcome,
        "observed_at": observed_at,
    }
    body["commercial_proof_hash"] = canonical_hash(body)
    return body
