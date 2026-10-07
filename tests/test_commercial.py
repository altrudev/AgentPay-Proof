import copy
import unittest

from src.commercial import (
    CapabilityOffer,
    CommercialIntentCapsule,
    evaluate_offer,
    make_commercial_proof,
    pareto_frontier,
    plan_commercial_action,
    plan_explanation,
)


NOW = 1_800_000_000


def capsule(**overrides):
    data = dict(
        capsule_id="capsule:release-qa",
        principal_id="user:test",
        purpose="release-validation",
        outcome="visual conformity >= 95 percent",
        maximum_spend_atomic=100_000,
        settlement_asset="USDC",
        allowed_capabilities=("browser.render.verify", "local.visual.compare"),
        allowed_disclosures=("rendered_page",),
        prohibited_disclosures=("repository_source", "private_messages"),
        minimum_evidence=("signed_execution_receipt", "visual_diff"),
        minimum_confidence_bps=9_500,
        maximum_credential_ttl_seconds=300,
        maximum_compute_units=20,
        maximum_retention_seconds=0,
        expires_at=NOW + 900,
        created_at=NOW,
        allowed_jurisdictions=("CA",),
        preference_order=("disclosure", "price", "retention", "compute", "latency", "confidence"),
        automatic_execution=False,
    )
    data.update(overrides)
    return CommercialIntentCapsule(**data)


def offer(offer_id, **overrides):
    data = dict(
        offer_id=offer_id,
        provider_id=f"provider:{offer_id}",
        capability="browser.render.verify",
        price_atomic=30_000,
        settlement_asset="USDC",
        required_disclosures=("rendered_page",),
        evidence=("signed_execution_receipt", "visual_diff"),
        expected_confidence_bps=9_700,
        credential_ttl_seconds=120,
        compute_units=4,
        retention_seconds=0,
        latency_ms=8_000,
        jurisdiction="CA",
        expires_at=NOW + 300,
    )
    data.update(overrides)
    return CapabilityOffer(**data)


class CommercialIntentTests(unittest.TestCase):
    def test_capsule_is_canonical_and_conflict_fails_closed(self):
        a = capsule(allowed_disclosures=("rendered_page", "rendered_page"))
        b = capsule(allowed_disclosures=("rendered_page",))
        self.assertEqual(a.digest, b.digest)
        with self.assertRaisesRegex(ValueError, "disclosure-policy-conflict"):
            capsule(
                allowed_disclosures=("repository_source",),
                prohibited_disclosures=("repository_source",),
            )

    def test_offer_inside_envelope_is_permitted(self):
        decision = evaluate_offer(capsule(), offer("safe"), now=NOW + 1)
        self.assertEqual(decision.decision, "PERMIT")
        self.assertEqual(decision.reasons, ("within-commercial-envelope",))

    def test_excess_disclosure_is_denied(self):
        decision = evaluate_offer(
            capsule(),
            offer("leaky", required_disclosures=("rendered_page", "repository_source")),
            now=NOW + 1,
        )
        self.assertEqual(decision.decision, "DENY")
        self.assertIn("disclosure-not-authorized", decision.reasons)
        self.assertIn("prohibited-disclosure-required", decision.reasons)

    def test_price_and_confidence_are_independent_authority_dimensions(self):
        decision = evaluate_offer(
            capsule(),
            offer("bad-economics", price_atomic=100_001, expected_confidence_bps=9_499),
            now=NOW + 1,
        )
        self.assertIn("price-exceeds-authority", decision.reasons)
        self.assertIn("confidence-below-target", decision.reasons)

    def test_retention_compute_credential_and_jurisdiction_fail_closed(self):
        decision = evaluate_offer(
            capsule(),
            offer(
                "scope-creep",
                retention_seconds=1,
                compute_units=21,
                credential_ttl_seconds=301,
                jurisdiction="US",
            ),
            now=NOW + 1,
        )
        self.assertEqual(decision.decision, "DENY")
        self.assertIn("retention-exceeds-authority", decision.reasons)
        self.assertIn("compute-exceeds-authority", decision.reasons)
        self.assertIn("credential-ttl-exceeds-authority", decision.reasons)
        self.assertIn("jurisdiction-not-authorized", decision.reasons)

    def test_required_evidence_is_mandatory(self):
        decision = evaluate_offer(
            capsule(),
            offer("weak-proof", evidence=("signed_execution_receipt",)),
            now=NOW + 1,
        )
        self.assertEqual(decision.decision, "DENY")
        self.assertIn("required-evidence-missing", decision.reasons)

    def test_expired_capsule_or_offer_cannot_be_selected(self):
        expired_capsule = capsule(expires_at=NOW + 1)
        decision = evaluate_offer(expired_capsule, offer("safe"), now=NOW + 2)
        self.assertIn("capsule-expired", decision.reasons)

        decision = evaluate_offer(
            capsule(),
            offer("expired-offer", expires_at=NOW),
            now=NOW + 1,
        )
        self.assertIn("offer-expired", decision.reasons)

    def test_pareto_frontier_excludes_dominated_offer(self):
        better = offer("better", price_atomic=20_000, latency_ms=5_000)
        worse = offer("worse", price_atomic=30_000, latency_ms=8_000)
        privacy = offer(
            "privacy",
            price_atomic=35_000,
            required_disclosures=(),
            latency_ms=10_000,
        )
        frontier = pareto_frontier([worse, privacy, better])
        self.assertEqual({item.offer_id for item in frontier}, {"better", "privacy"})

    def test_planner_rejects_unsafe_and_selects_privacy_first(self):
        safe = offer("safe", price_atomic=20_000)
        private = offer("private", price_atomic=40_000, required_disclosures=())
        leaky = offer("leaky", price_atomic=1, required_disclosures=("repository_source",))

        plan = plan_commercial_action(capsule(), [safe, private, leaky], now=NOW + 1)

        self.assertEqual(plan.selected_offer_id, "private")
        self.assertTrue(plan.requires_human_approval)
        self.assertEqual(plan.reason, "selected-smallest-justified-action")
        rejected = {item.offer_id: item for item in plan.rejected}
        self.assertIn("prohibited-disclosure-required", rejected["leaky"].reasons)

    def test_explicit_preference_order_can_choose_cost_first(self):
        intent = capsule(
            preference_order=("price", "disclosure", "retention", "compute", "latency", "confidence")
        )
        cheap = offer("cheap", price_atomic=20_000)
        private = offer("private", price_atomic=40_000, required_disclosures=())
        plan = plan_commercial_action(intent, [cheap, private], now=NOW + 1)
        self.assertEqual(plan.selected_offer_id, "cheap")

    def test_planner_never_manufactures_authority(self):
        plan = plan_commercial_action(
            capsule(maximum_spend_atomic=10_000),
            [offer("too-expensive", price_atomic=20_000)],
            now=NOW + 1,
        )
        self.assertIsNone(plan.selected_offer_id)
        self.assertEqual(plan.reason, "no-permitted-offer")
        self.assertTrue(plan.requires_human_approval)

    def test_automatic_execution_must_be_explicit_in_capsule(self):
        manual = plan_commercial_action(capsule(), [offer("safe")], now=NOW + 1)
        automatic = plan_commercial_action(
            capsule(automatic_execution=True),
            [offer("safe")],
            now=NOW + 1,
        )
        self.assertTrue(manual.requires_human_approval)
        self.assertFalse(automatic.requires_human_approval)

    def test_explanation_exposes_why_not_hidden_score(self):
        leaky = offer("leaky", required_disclosures=("repository_source",))
        safe = offer("safe")
        intent = capsule()
        plan = plan_commercial_action(intent, [leaky, safe], now=NOW + 1)
        explanation = plan_explanation(intent, [leaky, safe], plan)
        self.assertEqual(explanation["selected"]["offer_id"], "safe")
        self.assertEqual(explanation["selected"]["disclosures"], ["rendered_page"])
        self.assertEqual(explanation["rejected"][0]["offer_id"], "leaky")
        self.assertIn("plan_digest", explanation)

    def test_commercial_proof_binds_capsule_plan_authority_action_and_outcome(self):
        intent = capsule()
        safe = offer("safe")
        plan = plan_commercial_action(intent, [safe], now=NOW + 1)
        proof = make_commercial_proof(
            intent,
            plan,
            authority_digest="authority:abc",
            action_proof_hash="proof:def",
            outcome="target-satisfied",
            observed_at=NOW + 2,
        )
        self.assertEqual(proof["schema"], "agentpay-commercial-proof/1")
        self.assertEqual(proof["capsule_digest"], intent.digest)
        self.assertEqual(proof["plan_digest"], plan.digest)
        tampered = copy.deepcopy(proof)
        tampered["outcome"] = "different"
        self.assertNotEqual(tampered["commercial_proof_hash"], proof["commercial_proof_hash"])

    def test_commercial_proof_requires_a_selected_offer(self):
        intent = capsule()
        plan = plan_commercial_action(intent, [], now=NOW + 1)
        with self.assertRaisesRegex(ValueError, "commercial-proof-requires-selected-offer"):
            make_commercial_proof(
                intent,
                plan,
                authority_digest="a",
                action_proof_hash="b",
                outcome="c",
                observed_at=NOW + 2,
            )


if __name__ == "__main__":
    unittest.main()
