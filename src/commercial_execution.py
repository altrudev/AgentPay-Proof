from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Sequence

from src.commercial import (
    CapabilityOffer,
    CommercialIntentCapsule,
    CommercialPlan,
    OfferEvaluation,
    evaluate_offer,
    make_commercial_proof,
    plan_commercial_action,
    plan_explanation,
    verify_commercial_proof,
)
from src.model import canonical_hash


class CommercialExecutionError(RuntimeError):
    pass


_ALLOWED_TRANSITIONS = {
    "PREPARED": {"APPROVED", "ABORTED"},
    "APPROVED": {"DISPATCHED", "IN_DOUBT", "ABORTED"},
    "DISPATCHED": {"OBSERVED", "IN_DOUBT"},
    "IN_DOUBT": {"DISPATCHED", "OBSERVED"},
    "OBSERVED": {"CONSUMED"},
    "CONSUMED": set(),
    "ABORTED": set(),
}


@dataclass(frozen=True)
class CommercialGrant:
    grant_id: str
    capsule_digest: str
    plan_digest: str
    offer_digest: str
    offer_id: str
    provider_id: str
    capability: str
    exact_price_atomic: int
    settlement_asset: str
    disclosures: tuple[str, ...]
    evidence_required: tuple[str, ...]
    credential_ttl_seconds: int
    compute_units: int
    retention_seconds: int
    expires_at: int
    automatic_execution: bool

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": "agentpay-commercial-grant/1", **asdict(self)})


@dataclass(frozen=True)
class CommercialExecutionRecord:
    grant_id: str
    capsule_digest: str
    plan_digest: str
    grant_digest: str
    state: str
    action_id: str | None
    action_proof_hash: str | None


@dataclass(frozen=True)
class CommercialOutcomeAssessment:
    verdict: str
    target: str
    observed_confidence_bps: int
    evidence_digest: str
    observed_at: int
    reason: str

    @property
    def digest(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class ReferenceCapabilityResult:
    action_id: str
    action_receipt: dict[str, Any]
    artifact: dict[str, Any]


def project_commercial_grant(
    capsule: CommercialIntentCapsule,
    plan: CommercialPlan,
    offer: CapabilityOffer,
    *,
    now: int,
) -> CommercialGrant:
    if plan.capsule_digest != capsule.digest:
        raise CommercialExecutionError("plan-capsule-binding-mismatch")
    if plan.selected_offer_id != offer.offer_id or plan.selected_offer_digest != offer.digest:
        raise CommercialExecutionError("plan-offer-binding-mismatch")

    evaluation = evaluate_offer(capsule, offer, now=now)
    if evaluation.decision != "PERMIT":
        raise CommercialExecutionError("selected-offer-not-permitted")
    if now > capsule.expires_at or now > offer.expires_at:
        raise CommercialExecutionError("commercial-authority-expired")

    grant = CommercialGrant(
        grant_id="grant:" + canonical_hash({
            "capsule": capsule.digest,
            "plan": plan.digest,
            "offer": offer.digest,
        })[:32],
        capsule_digest=capsule.digest,
        plan_digest=plan.digest,
        offer_digest=offer.digest,
        offer_id=offer.offer_id,
        provider_id=offer.provider_id,
        capability=offer.capability,
        exact_price_atomic=offer.price_atomic,
        settlement_asset=offer.settlement_asset,
        disclosures=offer.required_disclosures,
        evidence_required=capsule.minimum_evidence,
        credential_ttl_seconds=offer.credential_ttl_seconds,
        compute_units=offer.compute_units,
        retention_seconds=offer.retention_seconds,
        expires_at=min(capsule.expires_at, offer.expires_at),
        automatic_execution=capsule.automatic_execution,
    )
    return grant


class CommercialExecutionJournal:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS commercial_executions (
                    grant_id TEXT PRIMARY KEY,
                    capsule_digest TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,
                    grant_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    approval_digest TEXT NOT NULL,
                    action_id TEXT,
                    action_proof_hash TEXT,
                    context_json TEXT NOT NULL
                )
                """
            )

    def reserve(
        self,
        grant: CommercialGrant,
        *,
        approval_digest: str,
        context_json: str,
    ) -> CommercialExecutionRecord:
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO commercial_executions(
                        grant_id,capsule_digest,plan_digest,grant_digest,state,
                        approval_digest,context_json
                    ) VALUES (?,?,?,?, 'PREPARED', ?, ?)
                    """,
                    (
                        grant.grant_id,
                        grant.capsule_digest,
                        grant.plan_digest,
                        grant.digest,
                        approval_digest,
                        context_json,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise CommercialExecutionError("commercial-grant-already-reserved") from exc
        return self.get(grant.grant_id)

    def get(self, grant_id: str) -> CommercialExecutionRecord:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                SELECT grant_id,capsule_digest,plan_digest,grant_digest,state,
                       action_id,action_proof_hash
                FROM commercial_executions WHERE grant_id = ?
                """,
                (grant_id,),
            ).fetchone()
        if row is None:
            raise CommercialExecutionError("commercial-execution-not-found")
        return CommercialExecutionRecord(**dict(row))

    def context(self, grant_id: str) -> dict[str, Any]:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT context_json FROM commercial_executions WHERE grant_id = ?",
                (grant_id,),
            ).fetchone()
        if row is None:
            raise CommercialExecutionError("commercial-execution-not-found")
        return json.loads(row["context_json"])

    def approval_digest(self, grant_id: str) -> str:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT approval_digest FROM commercial_executions WHERE grant_id = ?",
                (grant_id,),
            ).fetchone()
        if row is None:
            raise CommercialExecutionError("commercial-execution-not-found")
        return row["approval_digest"]

    def transition(
        self,
        grant_id: str,
        state: str,
        *,
        action_id: str | None = None,
        action_proof_hash: str | None = None,
    ) -> CommercialExecutionRecord:
        current = self.get(grant_id)
        if state not in _ALLOWED_TRANSITIONS.get(current.state, set()):
            raise CommercialExecutionError(f"invalid-commercial-transition:{current.state}->{state}")
        if current.action_id and action_id and current.action_id != action_id:
            raise CommercialExecutionError("commercial-action-id-mismatch")
        if current.action_proof_hash and action_proof_hash and current.action_proof_hash != action_proof_hash:
            raise CommercialExecutionError("commercial-action-proof-mismatch")

        final_action_id = action_id or current.action_id
        final_proof = action_proof_hash or current.action_proof_hash

        with closing(self._connect()) as conn, conn:
            changed = conn.execute(
                """
                UPDATE commercial_executions
                SET state = ?, action_id = ?, action_proof_hash = ?
                WHERE grant_id = ? AND state = ?
                """,
                (state, final_action_id, final_proof, grant_id, current.state),
            ).rowcount
        if changed != 1:
            raise CommercialExecutionError("commercial-execution-state-race")
        return self.get(grant_id)

    def approve(self, grant_id: str, supplied_approval_digest: str) -> CommercialExecutionRecord:
        expected = self.approval_digest(grant_id)
        if supplied_approval_digest != expected:
            raise CommercialExecutionError("commercial-approval-mismatch")
        return self.transition(grant_id, "APPROVED")

    def abort(self, grant_id: str) -> CommercialExecutionRecord:
        current = self.get(grant_id)
        if current.state not in {"PREPARED", "APPROVED"}:
            raise CommercialExecutionError(f"commercial-abort-not-allowed:{current.state}")
        return self.transition(grant_id, "ABORTED")

    def mark_dispatched(self, grant_id: str, action_id: str) -> CommercialExecutionRecord:
        if not action_id:
            raise CommercialExecutionError("commercial-action-id-required")
        return self.transition(grant_id, "DISPATCHED", action_id=action_id)

    def mark_in_doubt(self, grant_id: str, action_id: str | None = None) -> CommercialExecutionRecord:
        return self.transition(grant_id, "IN_DOUBT", action_id=action_id)

    def mark_observed(
        self,
        grant_id: str,
        *,
        action_id: str,
        action_proof_hash: str,
    ) -> CommercialExecutionRecord:
        if not action_id or not action_proof_hash:
            raise CommercialExecutionError("commercial-observation-binding-required")
        return self.transition(
            grant_id,
            "OBSERVED",
            action_id=action_id,
            action_proof_hash=action_proof_hash,
        )

    def consume(self, grant_id: str) -> CommercialExecutionRecord:
        return self.transition(grant_id, "CONSUMED")


def _approval_digest(grant: CommercialGrant, explanation: dict[str, Any]) -> str:
    return canonical_hash({
        "schema": "agentpay-commercial-approval/1",
        "grant_digest": grant.digest,
        "human_surface": explanation,
    })


def _reference_capability_execute(grant: CommercialGrant, payload: dict[str, Any]) -> ReferenceCapabilityResult:
    if grant.capability != "browser.render.verify":
        raise CommercialExecutionError("reference-capability-unsupported")
    if set(payload) - {"rendered_page_digest", "reference_digest"}:
        raise CommercialExecutionError("reference-payload-field-not-authorized")
    rendered = str(payload.get("rendered_page_digest", "")).strip()
    reference = str(payload.get("reference_digest", "")).strip()
    if not rendered or not reference:
        raise CommercialExecutionError("reference-payload-required")

    artifact = {
        "capability": grant.capability,
        "provider_id": grant.provider_id,
        "rendered_page_digest": rendered,
        "reference_digest": reference,
        "visual_diff": canonical_hash({"rendered": rendered, "reference": reference}),
        "confidence_bps": 9700,
        "disclosures_used": list(grant.disclosures),
        "retention_seconds": grant.retention_seconds,
    }
    action_receipt = {
        "schema": "agentpay-reference-action-receipt/1",
        "grant_digest": grant.digest,
        "provider_id": grant.provider_id,
        "capability": grant.capability,
        "artifact_digest": canonical_hash(artifact),
        "evidence": ["execution_receipt", "visual_diff"],
    }
    action_id = "action:" + canonical_hash(action_receipt)[:32]
    action_receipt["action_id"] = action_id
    action_receipt["action_proof_hash"] = canonical_hash(action_receipt)
    return ReferenceCapabilityResult(action_id, action_receipt, artifact)


def _assess_reference_outcome(
    capsule: CommercialIntentCapsule,
    grant: CommercialGrant,
    result: ReferenceCapabilityResult,
    *,
    now: int,
) -> CommercialOutcomeAssessment:
    artifact = result.artifact
    required = set(grant.evidence_required)
    produced = set(result.action_receipt.get("evidence", []))
    if required - produced:
        return CommercialOutcomeAssessment(
            "FAIL",
            capsule.outcome,
            int(artifact.get("confidence_bps", 0)),
            canonical_hash(result.action_receipt),
            now,
            "required-evidence-missing",
        )
    if set(artifact.get("disclosures_used", [])) != set(grant.disclosures):
        return CommercialOutcomeAssessment(
            "FAIL",
            capsule.outcome,
            int(artifact.get("confidence_bps", 0)),
            canonical_hash(result.action_receipt),
            now,
            "disclosure-observation-mismatch",
        )
    confidence = int(artifact.get("confidence_bps", 0))
    verdict = "PASS" if confidence >= capsule.minimum_confidence_bps else "FAIL"
    return CommercialOutcomeAssessment(
        verdict,
        capsule.outcome,
        confidence,
        canonical_hash(result.action_receipt),
        now,
        "target-satisfied" if verdict == "PASS" else "confidence-below-target",
    )


class CommercialCoordinator:
    """Commercial authority boundary.

    Companion may propose a plan. This coordinator creates an exact grant,
    persists it before approval, and refuses dispatch until approval is bound
    to the exact HIO explanation surface. Reference execution is deterministic
    and non-monetary; real payment remains behind the existing wallet boundary.
    """

    def __init__(self, journal: CommercialExecutionJournal):
        self.journal = journal

    def prepare(
        self,
        capsule: CommercialIntentCapsule,
        offers: Sequence[CapabilityOffer],
        *,
        now: int,
    ) -> dict[str, Any]:
        plan = plan_commercial_action(capsule, offers, now=now)
        if plan.selected_offer_id is None:
            return {
                "environment": "REFERENCE",
                "status": "DENIED",
                "plan": plan_explanation(capsule, offers, plan),
                "grant": None,
                "approval_digest": None,
            }
        selected = next(offer for offer in offers if offer.offer_id == plan.selected_offer_id)
        grant = project_commercial_grant(capsule, plan, selected, now=now)
        explanation = plan_explanation(capsule, offers, plan)
        approval_digest = _approval_digest(grant, explanation)
        context_json = json.dumps({
            "capsule": asdict(capsule),
            "offers": [asdict(offer) for offer in offers],
            "plan": {
                "capsule_digest": plan.capsule_digest,
                "selected_offer_digest": plan.selected_offer_digest,
                "selected_offer_id": plan.selected_offer_id,
                "permitted_offer_ids": plan.permitted_offer_ids,
                "rejected": [asdict(item) for item in plan.rejected],
                "frontier_offer_ids": plan.frontier_offer_ids,
                "requires_human_approval": plan.requires_human_approval,
                "reason": plan.reason,
            },
            "grant": asdict(grant),
            "explanation": explanation,
        }, sort_keys=True, separators=(",", ":"))
        self.journal.reserve(grant, approval_digest=approval_digest, context_json=context_json)

        return {
            "environment": "REFERENCE",
            "status": "PREPARED",
            "grant": {**asdict(grant), "digest": grant.digest},
            "plan": explanation,
            "approval_digest": approval_digest,
            "requires_human_approval": plan.requires_human_approval,
            "execution": "NOT_DISPATCHED",
        }

    def approve_and_execute_reference(
        self,
        grant_id: str,
        *,
        approval_digest: str,
        payload: dict[str, Any],
        now: int,
    ) -> dict[str, Any]:
        context = self.journal.context(grant_id)
        capsule = CommercialIntentCapsule(**context["capsule"])
        offers = tuple(CapabilityOffer(**item) for item in context["offers"])
        plan_raw = context["plan"]
        plan = CommercialPlan(
            capsule_digest=plan_raw["capsule_digest"],
            selected_offer_digest=plan_raw["selected_offer_digest"],
            selected_offer_id=plan_raw["selected_offer_id"],
            permitted_offer_ids=tuple(plan_raw["permitted_offer_ids"]),
            rejected=tuple(
                OfferEvaluation(
                    offer_id=item["offer_id"],
                    decision=item["decision"],
                    reasons=tuple(item["reasons"]),
                    disclosure_count=item["disclosure_count"],
                )
                for item in plan_raw["rejected"]
            ),
            frontier_offer_ids=tuple(plan_raw["frontier_offer_ids"]),
            requires_human_approval=plan_raw["requires_human_approval"],
            reason=plan_raw["reason"],
        )
        selected = next(offer for offer in offers if offer.offer_id == plan.selected_offer_id)
        grant = project_commercial_grant(capsule, plan, selected, now=min(now, selected.expires_at))
        if grant.grant_id != grant_id:
            raise CommercialExecutionError("commercial-grant-reconstruction-mismatch")
        if now > grant.expires_at:
            raise CommercialExecutionError("commercial-grant-expired")

        current = self.journal.get(grant_id)
        if current.state == "PREPARED":
            self.journal.approve(grant_id, approval_digest)
        elif current.state != "APPROVED":
            raise CommercialExecutionError(f"commercial-execution-not-approvable:{current.state}")

        try:
            result = _reference_capability_execute(grant, payload)
        except Exception as exc:
            self.journal.mark_in_doubt(grant_id)
            raise CommercialExecutionError("commercial-reference-dispatch-unknown") from exc

        self.journal.mark_dispatched(grant_id, result.action_id)
        assessment = _assess_reference_outcome(capsule, grant, result, now=now)
        if assessment.verdict != "PASS":
            self.journal.mark_in_doubt(grant_id, result.action_id)
            raise CommercialExecutionError("commercial-outcome-not-satisfied")

        self.journal.mark_observed(
            grant_id,
            action_id=result.action_id,
            action_proof_hash=result.action_receipt["action_proof_hash"],
        )
        proof = make_commercial_proof(
            capsule,
            plan,
            authority_digest=grant.digest,
            action_proof_hash=result.action_receipt["action_proof_hash"],
            outcome=assessment.reason,
            observed_at=now,
        )
        verification = verify_commercial_proof(proof)
        if verification["verdict"] != "VERIFIED":
            raise CommercialExecutionError("commercial-proof-verification-failed")
        self.journal.consume(grant_id)
        return {
            "environment": "REFERENCE",
            "status": "VERIFIED",
            "execution_state": "CONSUMED",
            "grant": {**asdict(grant), "digest": grant.digest},
            "action_receipt": result.action_receipt,
            "artifact": result.artifact,
            "outcome_assessment": {**asdict(assessment), "digest": assessment.digest},
            "commercial_proof": proof,
            "verification": verification,
            "monetary_settlement": "NOT_PERFORMED",
        }
