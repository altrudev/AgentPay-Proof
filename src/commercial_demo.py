from __future__ import annotations

from dataclasses import asdict

from src.commercial import (
    CapabilityOffer,
    CommercialIntentCapsule,
    plan_commercial_action,
    plan_explanation,
)


def release_validation_demo(*, now: int) -> dict:
    capsule = CommercialIntentCapsule(
        capsule_id="capsule:release-validation-demo",
        principal_id="principal:demo",
        purpose="release-validation",
        outcome="Reach at least 95% verification confidence without disclosing repository source.",
        maximum_spend_atomic=100_000,
        settlement_asset="USDC",
        allowed_capabilities=("local.visual.compare", "browser.render.verify"),
        allowed_disclosures=("rendered_page",),
        prohibited_disclosures=("repository_source", "private_messages", "credentials"),
        minimum_evidence=("signed_execution_receipt", "visual_diff"),
        minimum_confidence_bps=9_500,
        maximum_credential_ttl_seconds=300,
        maximum_compute_units=20,
        maximum_retention_seconds=0,
        expires_at=now + 900,
        created_at=now,
        allowed_jurisdictions=("CA",),
        automatic_execution=False,
    )

    offers = (
        CapabilityOffer(
            offer_id="local-visual-compare",
            provider_id="local:frequency",
            capability="local.visual.compare",
            price_atomic=0,
            settlement_asset="USDC",
            required_disclosures=(),
            evidence=("signed_execution_receipt", "visual_diff"),
            expected_confidence_bps=8_800,
            credential_ttl_seconds=0,
            compute_units=3,
            retention_seconds=0,
            latency_ms=1_200,
            jurisdiction="CA",
            expires_at=now + 600,
        ),
        CapabilityOffer(
            offer_id="source-code-validator",
            provider_id="provider:source-required",
            capability="browser.render.verify",
            price_atomic=10_000,
            settlement_asset="USDC",
            required_disclosures=("repository_source",),
            evidence=("signed_execution_receipt", "visual_diff"),
            expected_confidence_bps=9_900,
            credential_ttl_seconds=120,
            compute_units=5,
            retention_seconds=0,
            latency_ms=4_000,
            jurisdiction="CA",
            expires_at=now + 300,
        ),
        CapabilityOffer(
            offer_id="privacy-render-validator",
            provider_id="provider:render-only",
            capability="browser.render.verify",
            price_atomic=30_000,
            settlement_asset="USDC",
            required_disclosures=("rendered_page",),
            evidence=("signed_execution_receipt", "visual_diff"),
            expected_confidence_bps=9_700,
            credential_ttl_seconds=120,
            compute_units=5,
            retention_seconds=0,
            latency_ms=8_000,
            jurisdiction="CA",
            expires_at=now + 300,
        ),
        CapabilityOffer(
            offer_id="premium-render-validator",
            provider_id="provider:premium",
            capability="browser.render.verify",
            price_atomic=80_000,
            settlement_asset="USDC",
            required_disclosures=("rendered_page",),
            evidence=("signed_execution_receipt", "visual_diff"),
            expected_confidence_bps=9_700,
            credential_ttl_seconds=120,
            compute_units=7,
            retention_seconds=0,
            latency_ms=12_000,
            jurisdiction="CA",
            expires_at=now + 300,
        ),
    )

    plan = plan_commercial_action(capsule, offers, now=now)
    return {
        "schema": "agentpay-commercial-demo/1",
        "capsule": {**asdict(capsule), "digest": capsule.digest},
        "offers": [{**asdict(offer), "digest": offer.digest} for offer in offers],
        "plan": {
            "capsule_digest": plan.capsule_digest,
            "selected_offer_digest": plan.selected_offer_digest,
            "selected_offer_id": plan.selected_offer_id,
            "permitted_offer_ids": list(plan.permitted_offer_ids),
            "rejected": [asdict(item) for item in plan.rejected],
            "frontier_offer_ids": list(plan.frontier_offer_ids),
            "requires_human_approval": plan.requires_human_approval,
            "reason": plan.reason,
            "digest": plan.digest,
        },
        "explanation": plan_explanation(capsule, offers, plan),
        "execution": {
            "status": "NOT_EXECUTED",
            "reason": "planning-demo-only",
        },
    }
