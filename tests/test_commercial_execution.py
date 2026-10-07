import os
import tempfile
import unittest

from src.commercial import CapabilityOffer, CommercialIntentCapsule
from src.commercial_execution import (
    CommercialCoordinator,
    CommercialExecutionError,
    CommercialExecutionJournal,
    project_commercial_grant,
    verify_commercial_bundle,
)


NOW = 1_800_000_000


def capsule(**overrides):
    data = dict(
        capsule_id="capsule:release",
        principal_id="principal:test",
        purpose="release-validation",
        outcome="Reach at least 95% visual confidence.",
        maximum_spend_atomic=50_000,
        settlement_asset="USDC",
        allowed_capabilities=("browser.render.verify",),
        allowed_disclosures=("rendered_page",),
        prohibited_disclosures=("repository_source",),
        minimum_evidence=("execution_receipt", "visual_diff"),
        minimum_confidence_bps=9_500,
        maximum_credential_ttl_seconds=300,
        maximum_compute_units=20,
        maximum_retention_seconds=0,
        expires_at=NOW + 900,
        created_at=NOW,
        allowed_jurisdictions=("CA",),
        automatic_execution=False,
    )
    data.update(overrides)
    return CommercialIntentCapsule(**data)


def offer(offer_id="render-safe", **overrides):
    data = dict(
        offer_id=offer_id,
        provider_id="provider:render-only",
        capability="browser.render.verify",
        price_atomic=30_000,
        settlement_asset="USDC",
        required_disclosures=("rendered_page",),
        evidence=("execution_receipt", "visual_diff"),
        expected_confidence_bps=9_700,
        credential_ttl_seconds=120,
        compute_units=5,
        retention_seconds=0,
        latency_ms=8_000,
        jurisdiction="CA",
        expires_at=NOW + 300,
    )
    data.update(overrides)
    return CapabilityOffer(**data)


class CommercialExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.journal = CommercialExecutionJournal(self.path)
        self.coordinator = CommercialCoordinator(self.journal)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_prepare_reserves_exact_grant_without_dispatch(self):
        out = self.coordinator.prepare(capsule(), [offer()], now=NOW + 1)
        self.assertEqual(out["status"], "PREPARED")
        self.assertEqual(out["execution"], "NOT_DISPATCHED")
        self.assertTrue(out["requires_human_approval"])
        record = self.journal.get(out["grant"]["grant_id"])
        self.assertEqual(record.state, "PREPARED")
        self.assertIsNone(record.action_id)
        self.assertIsNone(record.action_proof_hash)

    def test_approval_is_bound_to_exact_hio_surface(self):
        out = self.coordinator.prepare(capsule(), [offer()], now=NOW + 1)
        grant_id = out["grant"]["grant_id"]
        with self.assertRaisesRegex(CommercialExecutionError, "commercial-approval-mismatch"):
            self.coordinator.approve_and_execute_reference(
                grant_id,
                approval_digest="wrong",
                payload={"rendered_page_digest": "rendered:a", "reference_digest": "reference:b"},
                now=NOW + 2,
            )
        self.assertEqual(self.journal.get(grant_id).state, "PREPARED")

    def test_exact_approval_executes_once_and_produces_commercial_proof(self):
        out = self.coordinator.prepare(capsule(), [offer()], now=NOW + 1)
        result = self.coordinator.approve_and_execute_reference(
            out["grant"]["grant_id"],
            approval_digest=out["approval_digest"],
            payload={"rendered_page_digest": "rendered:a", "reference_digest": "reference:b"},
            now=NOW + 2,
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["execution_state"], "CONSUMED")
        self.assertEqual(result["verification"], {"verdict": "VERIFIED", "errors": []})
        self.assertEqual(result["monetary_settlement"], "NOT_PERFORMED")
        self.assertEqual(result["outcome_assessment"]["verdict"], "PASS")
        self.assertEqual(self.journal.get(out["grant"]["grant_id"]).state, "CONSUMED")

    def test_bundle_verifier_rejects_inner_artifact_substitution(self):
        out = self.coordinator.prepare(capsule(), [offer()], now=NOW + 1)
        result = self.coordinator.approve_and_execute_reference(
            out["grant"]["grant_id"],
            approval_digest=out["approval_digest"],
            payload={"rendered_page_digest": "rendered:a", "reference_digest": "reference:b"},
            now=NOW + 2,
        )
        context = self.journal.context(out["grant"]["grant_id"])
        from src.commercial import CommercialPlan, OfferEvaluation
        raw = context["plan"]
        plan = CommercialPlan(
            raw["capsule_digest"],
            raw["selected_offer_digest"],
            raw["selected_offer_id"],
            tuple(raw["permitted_offer_ids"]),
            tuple(
                OfferEvaluation(
                    item["offer_id"], item["decision"], tuple(item["reasons"]), item["disclosure_count"]
                ) for item in raw["rejected"]
            ),
            tuple(raw["frontier_offer_ids"]),
            raw["requires_human_approval"],
            raw["reason"],
        )
        cap = CommercialIntentCapsule(**context["capsule"])
        selected = next(CapabilityOffer(**item) for item in context["offers"] if item["offer_id"] == plan.selected_offer_id)
        grant = project_commercial_grant(cap, plan, selected, now=NOW + 1)
        from src.commercial_execution import CommercialOutcomeAssessment
        assessment_raw = result["outcome_assessment"]
        assessment = CommercialOutcomeAssessment(
            verdict=assessment_raw["verdict"],
            target=assessment_raw["target"],
            observed_confidence_bps=assessment_raw["observed_confidence_bps"],
            evidence_digest=assessment_raw["evidence_digest"],
            observed_at=assessment_raw["observed_at"],
            reason=assessment_raw["reason"],
        )
        tampered_artifact = dict(result["artifact"])
        tampered_artifact["confidence_bps"] = 9999
        verdict = verify_commercial_bundle(
            capsule=cap,
            plan=plan,
            offer=selected,
            grant=grant,
            action_receipt=result["action_receipt"],
            artifact=tampered_artifact,
            assessment=assessment,
            proof=result["commercial_proof"],
        )
        self.assertEqual(verdict["verdict"], "NOT VERIFIED")
        self.assertIn("action-artifact-binding-mismatch", verdict["errors"])
        self.assertIn("assessment-confidence-binding-mismatch", verdict["errors"])

    def test_consumed_grant_cannot_execute_again(self):
        out = self.coordinator.prepare(capsule(), [offer()], now=NOW + 1)
        kwargs = dict(
            grant_id=out["grant"]["grant_id"],
            approval_digest=out["approval_digest"],
            payload={"rendered_page_digest": "rendered:a", "reference_digest": "reference:b"},
            now=NOW + 2,
        )
        self.coordinator.approve_and_execute_reference(**kwargs)
        with self.assertRaisesRegex(CommercialExecutionError, "commercial-execution-not-approvable:CONSUMED"):
            self.coordinator.approve_and_execute_reference(**kwargs)

    def test_payload_cannot_smuggle_unapproved_fields(self):
        out = self.coordinator.prepare(capsule(), [offer()], now=NOW + 1)
        with self.assertRaisesRegex(CommercialExecutionError, "commercial-reference-dispatch-unknown"):
            self.coordinator.approve_and_execute_reference(
                out["grant"]["grant_id"],
                approval_digest=out["approval_digest"],
                payload={
                    "rendered_page_digest": "rendered:a",
                    "reference_digest": "reference:b",
                    "repository_source": "secret",
                },
                now=NOW + 2,
            )
        self.assertEqual(self.journal.get(out["grant"]["grant_id"]).state, "IN_DOUBT")

    def test_expired_grant_cannot_execute(self):
        intent = capsule(expires_at=NOW + 3)
        candidate = offer(expires_at=NOW + 3)
        out = self.coordinator.prepare(intent, [candidate], now=NOW + 1)
        with self.assertRaisesRegex(CommercialExecutionError, "commercial-grant-expired"):
            self.coordinator.approve_and_execute_reference(
                out["grant"]["grant_id"],
                approval_digest=out["approval_digest"],
                payload={"rendered_page_digest": "rendered:a", "reference_digest": "reference:b"},
                now=NOW + 4,
            )
        self.assertEqual(self.journal.get(out["grant"]["grant_id"]).state, "PREPARED")

    def test_denied_plan_creates_no_grant(self):
        unsafe = offer(required_disclosures=("repository_source",))
        out = self.coordinator.prepare(capsule(), [unsafe], now=NOW + 1)
        self.assertEqual(out["status"], "DENIED")
        self.assertIsNone(out["grant"])
        self.assertIsNone(out["approval_digest"])

    def test_grant_projection_rejects_plan_offer_substitution(self):
        safe = offer("safe")
        other = offer("other", provider_id="provider:other")
        prepared = self.coordinator.prepare(capsule(), [safe, other], now=NOW + 1)
        context = self.journal.context(prepared["grant"]["grant_id"])
        self.assertEqual(context["grant"]["offer_id"], prepared["grant"]["offer_id"])
        # A different offer cannot be projected under the selected plan.
        from src.commercial import CommercialPlan, OfferEvaluation
        raw = context["plan"]
        plan = CommercialPlan(
            raw["capsule_digest"],
            raw["selected_offer_digest"],
            raw["selected_offer_id"],
            tuple(raw["permitted_offer_ids"]),
            tuple(
                OfferEvaluation(
                    item["offer_id"], item["decision"], tuple(item["reasons"]), item["disclosure_count"]
                ) for item in raw["rejected"]
            ),
            tuple(raw["frontier_offer_ids"]),
            raw["requires_human_approval"],
            raw["reason"],
        )
        substituted = other if plan.selected_offer_id != other.offer_id else safe
        with self.assertRaisesRegex(CommercialExecutionError, "plan-offer-binding-mismatch"):
            project_commercial_grant(capsule(), plan, substituted, now=NOW + 1)


if __name__ == "__main__":
    unittest.main()
