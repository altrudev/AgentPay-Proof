from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any

from src.commercial import make_commercial_proof
from src.commercial_execution import (
    CommercialExecutionError,
    CommercialExecutionJournal,
    ReferenceCapabilityResult,
    assess_reference_outcome,
    execute_reference_capability,
    reconstruct_commercial_context,
    validate_reference_payload,
    verify_commercial_bundle,
)
from src.commercial_live import CapabilityRoute
from src.live import LiveConfig
from src.model import canonical_hash
from src.provider_admission import ProviderAdmission, ProviderBinding, ProviderRegistry
from src.settlement import JsonRpcClient, SettlementError
from src.x402 import (
    EIP3009Authorization,
    X402Error,
    X402Facilitator,
    X402Requirement,
    assert_verify_response,
    new_authorization,
    observe_eip3009_settlement,
    payment_payload,
    select_exact_eip3009_requirement,
    settlement_transaction,
    validate_signature,
    wallet_sign_request,
)


class CommercialX402Error(RuntimeError):
    pass


_X402_TRANSITIONS = {
    "PREPARED": {"SIGNING", "ABORTED"},
    "SIGNING": {"VERIFIED", "ABORTED"},
    "VERIFIED": {"RESOURCE_DISPATCHED", "ABORTED"},
    "RESOURCE_DISPATCHED": {"RESOURCE_EXECUTED", "IN_DOUBT"},
    "RESOURCE_EXECUTED": {"SETTLEMENT_PENDING", "IN_DOUBT"},
    "SETTLEMENT_PENDING": {"SETTLED", "IN_DOUBT"},
    "SETTLED": {"OBSERVED", "IN_DOUBT"},
    "IN_DOUBT": {"SETTLED", "OBSERVED"},
    "OBSERVED": {"CONSUMED"},
    "CONSUMED": set(),
    "ABORTED": set(),
}


@dataclass(frozen=True)
class X402ExecutionRecord:
    execution_id: str
    grant_id: str
    state: str
    nonce: str
    transaction_hash: str | None


class X402ExecutionJournal:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS x402_executions (
                    execution_id TEXT PRIMARY KEY,
                    grant_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    nonce TEXT NOT NULL UNIQUE,
                    approval_digest TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    transaction_hash TEXT
                )
                """
            )

    def reserve(
        self,
        *,
        execution_id: str,
        grant_id: str,
        nonce: str,
        approval_digest: str,
        context: dict[str, Any],
    ) -> X402ExecutionRecord:
        context_json = json.dumps(context, sort_keys=True, separators=(",", ":"))
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO x402_executions(
                        execution_id,grant_id,state,nonce,approval_digest,context_json
                    ) VALUES (?,?, 'PREPARED', ?, ?, ?)
                    """,
                    (execution_id, grant_id, nonce, approval_digest, context_json),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_grant(grant_id)
            if existing is None:
                raise CommercialX402Error("x402-execution-reservation-conflict") from exc
            if self.context(existing.execution_id) != context:
                raise CommercialX402Error("x402-execution-context-mismatch") from exc
            if self.approval_digest(existing.execution_id) != approval_digest:
                raise CommercialX402Error("x402-execution-approval-context-mismatch") from exc
            return existing
        return self.get(execution_id)

    def get(self, execution_id: str) -> X402ExecutionRecord:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT execution_id,grant_id,state,nonce,transaction_hash FROM x402_executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
        if row is None:
            raise CommercialX402Error("x402-execution-not-found")
        return X402ExecutionRecord(**dict(row))

    def get_by_grant(self, grant_id: str) -> X402ExecutionRecord | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT execution_id,grant_id,state,nonce,transaction_hash FROM x402_executions WHERE grant_id=?",
                (grant_id,),
            ).fetchone()
        return X402ExecutionRecord(**dict(row)) if row is not None else None

    def context(self, execution_id: str) -> dict[str, Any]:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT context_json FROM x402_executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
        if row is None:
            raise CommercialX402Error("x402-execution-not-found")
        return json.loads(row["context_json"])

    def replace_context(self, execution_id: str, context: dict[str, Any]) -> None:
        payload = json.dumps(context, sort_keys=True, separators=(",", ":"))
        with closing(self._connect()) as conn, conn:
            changed = conn.execute(
                "UPDATE x402_executions SET context_json=? WHERE execution_id=?",
                (payload, execution_id),
            ).rowcount
        if changed != 1:
            raise CommercialX402Error("x402-context-update-failed")

    def approval_digest(self, execution_id: str) -> str:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT approval_digest FROM x402_executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
        if row is None:
            raise CommercialX402Error("x402-execution-not-found")
        return str(row["approval_digest"])

    def transition(
        self,
        execution_id: str,
        state: str,
        *,
        transaction_hash: str | None = None,
    ) -> X402ExecutionRecord:
        current = self.get(execution_id)
        if state not in _X402_TRANSITIONS.get(current.state, set()):
            raise CommercialX402Error(f"invalid-x402-transition:{current.state}->{state}")
        tx_hash = transaction_hash or current.transaction_hash
        if current.transaction_hash and transaction_hash and current.transaction_hash.lower() != transaction_hash.lower():
            raise CommercialX402Error("x402-transaction-hash-substitution")
        with closing(self._connect()) as conn, conn:
            changed = conn.execute(
                "UPDATE x402_executions SET state=?, transaction_hash=? WHERE execution_id=? AND state=?",
                (state, tx_hash, execution_id, current.state),
            ).rowcount
        if changed != 1:
            raise CommercialX402Error("x402-state-race")
        return self.get(execution_id)


class CommercialX402Coordinator:
    """Frequency-governed x402 exact/EIP-3009 authorization flow.

    Ordering is intentionally x402 v2 authorization flow:
    verify signature -> execute resource -> settle -> independently observe.
    The coordinator never receives a private key and never signs on behalf of
    the payer.
    """

    def __init__(
        self,
        *,
        commercial_journal: CommercialExecutionJournal,
        x402_journal: X402ExecutionJournal,
        live_config: LiveConfig,
        provider_registry: ProviderRegistry,
        facilitator: X402Facilitator,
        rpc: JsonRpcClient | None = None,
    ):
        self.commercial_journal = commercial_journal
        self.x402_journal = x402_journal
        self.live_config = live_config.validate()
        self.provider_registry = provider_registry
        self.facilitator = facilitator
        self.rpc = rpc or JsonRpcClient(self.live_config.rpc_url)

    def _validate_context(self, execution_id: str, context: dict[str, Any]) -> tuple[CapabilityRoute, X402Requirement, EIP3009Authorization]:
        try:
            route = CapabilityRoute(**context["route"])
            requirement = X402Requirement(**context["requirement"])
            authorization = EIP3009Authorization(**context["authorization"])
            binding = ProviderBinding(**context["provider_binding"])
            admission = ProviderAdmission(**context["provider_admission"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CommercialX402Error("x402-context-invalid") from exc
        if context.get("route_digest") != route.digest:
            raise CommercialX402Error("x402-route-context-mismatch")
        if context.get("requirement_digest") != requirement.digest:
            raise CommercialX402Error("x402-requirement-context-mismatch")
        if context.get("authorization_digest") != authorization.digest:
            raise CommercialX402Error("x402-authorization-context-mismatch")
        if context.get("capability_payload_digest") != canonical_hash(context.get("capability_payload")):
            raise CommercialX402Error("x402-capability-payload-context-mismatch")
        if binding.digest != route.provider_binding_digest:
            raise CommercialX402Error("x402-provider-binding-context-mismatch")
        if admission.digest != route.provider_admission_digest or admission.binding_digest != binding.digest:
            raise CommercialX402Error("x402-provider-admission-context-mismatch")
        if requirement.chain_id != route.payment_chain_id:
            raise CommercialX402Error("x402-route-chain-context-mismatch")
        if requirement.asset != route.payment_asset_contract:
            raise CommercialX402Error("x402-route-asset-context-mismatch")
        if requirement.pay_to != route.payment_recipient:
            raise CommercialX402Error("x402-route-recipient-context-mismatch")
        if requirement.amount != route.payment_amount_atomic:
            raise CommercialX402Error("x402-route-amount-context-mismatch")
        if authorization.to != requirement.pay_to or authorization.value != requirement.amount:
            raise CommercialX402Error("x402-authorization-requirement-context-mismatch")
        expected_approval = canonical_hash({
            "schema": "agentpay-x402-execution-approval/1",
            "grant_digest": context.get("grant_digest"),
            "route_digest": route.digest,
            "requirement_digest": requirement.digest,
            "authorization_digest": authorization.digest,
            "capability_payload_digest": context.get("capability_payload_digest"),
            "hio": context.get("hio"),
        })
        if context.get("execution_approval_digest") != expected_approval:
            raise CommercialX402Error("x402-execution-approval-context-mismatch")
        if self.x402_journal.approval_digest(execution_id) != expected_approval:
            raise CommercialX402Error("x402-journal-approval-context-mismatch")
        return route, requirement, authorization

    def _route_and_requirement(
        self,
        grant_id: str,
        payment_required: dict[str, Any],
        *,
        now: int,
    ):
        capsule, offers, plan, selected, grant, explanation = reconstruct_commercial_context(
            self.commercial_journal, grant_id, now=now
        )
        try:
            binding, admission = self.provider_registry.require(grant.provider_id, grant.capability, now=now)
        except ValueError as exc:
            raise CommercialX402Error(str(exc)) from exc
        if not binding.adapter_id.startswith("https://"):
            raise CommercialX402Error("x402-provider-adapter-not-https")
        if binding.payment_recipient.lower() != self.live_config.recipient.lower():
            raise CommercialX402Error("x402-provider-recipient-config-mismatch")
        if grant.exact_price_atomic > self.live_config.maximum_amount_atomic:
            raise CommercialX402Error("x402-price-exceeds-live-authority")
        try:
            requirement = select_exact_eip3009_requirement(
                payment_required,
                resource_url=binding.adapter_id,
                chain_id=self.live_config.chain_id,
                asset=self.live_config.asset_contract,
                pay_to=binding.payment_recipient,
                amount=grant.exact_price_atomic,
            )
        except X402Error as exc:
            raise CommercialX402Error(str(exc)) from exc
        route_body = {
            "offer_digest": selected.digest,
            "provider_id": grant.provider_id,
            "capability": grant.capability,
            "adapter_id": binding.adapter_id,
            "provider_binding_digest": binding.digest,
            "provider_admission_digest": admission.digest,
            "request_schema": binding.request_schema,
            "observation_schema": binding.observation_schema,
            "payment_chain_id": requirement.chain_id,
            "payment_asset_contract": requirement.asset,
            "payment_recipient": requirement.pay_to,
            "payment_amount_atomic": requirement.amount,
            "expires_at": min(grant.expires_at, selected.expires_at, now + requirement.max_timeout_seconds),
        }
        route_id = "route:x402:" + canonical_hash(route_body)[:28]
        route = CapabilityRoute(route_id=route_id, **route_body)
        return capsule, offers, plan, selected, grant, explanation, binding, admission, route, requirement

    def prepare(
        self,
        grant_id: str,
        *,
        commercial_approval_digest: str,
        capability_payload: dict[str, Any],
        payment_required: dict[str, Any],
        payer: str,
        now: int,
    ) -> dict[str, Any]:
        (
            capsule, offers, plan, selected, grant, explanation,
            binding, admission, route, requirement,
        ) = self._route_and_requirement(grant_id, payment_required, now=now)
        validate_reference_payload(grant, capability_payload)
        if self.commercial_journal.get(grant_id).state != "PREPARED":
            raise CommercialX402Error("x402-commercial-grant-not-prepared")
        if self.commercial_journal.approval_digest(grant_id) != commercial_approval_digest:
            raise CommercialX402Error("commercial-approval-mismatch")

        existing = self.x402_journal.get_by_grant(grant_id)
        if existing is not None:
            context = self.x402_journal.context(existing.execution_id)
            if context.get("input_binding_digest") != canonical_hash({
                "capability_payload": capability_payload,
                "payment_required": payment_required,
                "payer": payer.lower(),
            }):
                raise CommercialX402Error("x402-execution-context-mismatch")
            return self._prepared_response(existing.execution_id, context)

        try:
            authorization = new_authorization(
                requirement,
                payer=payer,
                now=now,
                authority_expires_at=route.expires_at,
            )
        except X402Error as exc:
            raise CommercialX402Error(str(exc)) from exc
        execution_id = "x402:" + canonical_hash({
            "grant": grant.digest,
            "route": route.digest,
            "authorization": authorization.digest,
        })[:32]
        hio = {
            "provider_id": grant.provider_id,
            "capability": grant.capability,
            "resource": requirement.resource_url,
            "amount_atomic": requirement.amount,
            "asset": grant.settlement_asset,
            "network": requirement.network,
            "pay_to": requirement.pay_to,
            "valid_after": authorization.valid_after,
            "valid_before": authorization.valid_before,
            "one_time_nonce": authorization.nonce,
            "disclosures": list(grant.disclosures),
            "retention_seconds": grant.retention_seconds,
            "payment_flow": requirement.payment_flow,
            "asset_transfer_method": requirement.asset_transfer_method,
            "token_domain_name": requirement.token_name,
            "token_domain_version": requirement.token_version,
            "gas_paid_by_facilitator": True,
            "requires_wallet_signature": True,
        }
        execution_approval_digest = canonical_hash({
            "schema": "agentpay-x402-execution-approval/1",
            "grant_digest": grant.digest,
            "route_digest": route.digest,
            "requirement_digest": requirement.digest,
            "authorization_digest": authorization.digest,
            "capability_payload_digest": canonical_hash(capability_payload),
            "hio": hio,
        })
        input_binding_digest = canonical_hash({
            "capability_payload": capability_payload,
            "payment_required": payment_required,
            "payer": payer.lower(),
        })
        context = {
            "grant_digest": grant.digest,
            "route": asdict(route),
            "route_digest": route.digest,
            "provider_binding": asdict(binding),
            "provider_admission": asdict(admission),
            "requirement": asdict(requirement),
            "requirement_digest": requirement.digest,
            "authorization": asdict(authorization),
            "authorization_digest": authorization.digest,
            "capability_payload": capability_payload,
            "capability_payload_digest": canonical_hash(capability_payload),
            "commercial_approval_digest": commercial_approval_digest,
            "execution_approval_digest": execution_approval_digest,
            "input_binding_digest": input_binding_digest,
            "hio": hio,
        }
        self.x402_journal.reserve(
            execution_id=execution_id,
            grant_id=grant_id,
            nonce=authorization.nonce,
            approval_digest=execution_approval_digest,
            context=context,
        )
        return self._prepared_response(execution_id, context)

    def _prepared_response(self, execution_id: str, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "environment": "LIVE",
            "rail": "x402-v2-exact-eip3009",
            "status": "AWAITING_EXECUTION_APPROVAL",
            "execution_id": execution_id,
            "grant_digest": context["grant_digest"],
            "route": {**context["route"], "digest": context["route_digest"]},
            "requirement": context["requirement"],
            "authorization": context["authorization"],
            "execution_approval_digest": context["execution_approval_digest"],
            "wallet_request": None,
            "hio": context["hio"],
        }

    def confirm(
        self,
        execution_id: str,
        *,
        execution_approval_digest: str,
        now: int,
    ) -> dict[str, Any]:
        record = self.x402_journal.get(execution_id)
        context = self.x402_journal.context(execution_id)
        if record.state != "PREPARED":
            raise CommercialX402Error(f"x402-confirm-not-allowed:{record.state}")
        if self.x402_journal.approval_digest(execution_id) != execution_approval_digest:
            raise CommercialX402Error("x402-execution-approval-mismatch")
        route, requirement, authorization = self._validate_context(execution_id, context)
        if now <= authorization.valid_after or now >= authorization.valid_before:
            raise CommercialX402Error("x402-authorization-not-current")
        try:
            binding, admission = self.provider_registry.require(route.provider_id, route.capability, now=now)
        except ValueError as exc:
            raise CommercialX402Error(str(exc)) from exc
        if binding.digest != route.provider_binding_digest or admission.digest != route.provider_admission_digest:
            raise CommercialX402Error("x402-provider-admission-changed")

        commercial = self.commercial_journal.get(record.grant_id)
        if commercial.state == "PREPARED":
            self.commercial_journal.approve(record.grant_id, context["commercial_approval_digest"])
        elif commercial.state != "APPROVED":
            raise CommercialX402Error(f"x402-commercial-confirm-not-allowed:{commercial.state}")
        self.x402_journal.transition(execution_id, "SIGNING")
        return {
            "environment": "LIVE",
            "rail": "x402-v2-exact-eip3009",
            "status": "AWAITING_WALLET_SIGNATURE",
            "execution_id": execution_id,
            "wallet_request": wallet_sign_request(requirement, authorization),
            "hio": context["hio"],
        }

    def submit_signature_and_execute(
        self,
        execution_id: str,
        *,
        signature: str,
        now: int,
    ) -> dict[str, Any]:
        record = self.x402_journal.get(execution_id)
        if record.state != "SIGNING":
            raise CommercialX402Error(f"x402-signature-not-allowed:{record.state}")
        context = self.x402_journal.context(execution_id)
        route, requirement, authorization = self._validate_context(execution_id, context)
        try:
            active_binding, active_admission = self.provider_registry.require(
                route.provider_id, route.capability, now=now
            )
        except ValueError as exc:
            raise CommercialX402Error(str(exc)) from exc
        if active_binding.digest != route.provider_binding_digest or active_admission.digest != route.provider_admission_digest:
            raise CommercialX402Error("x402-provider-admission-changed")
        try:
            signature = validate_signature(signature)
            payload = payment_payload(requirement, authorization, signature)
        except X402Error as exc:
            raise CommercialX402Error(str(exc)) from exc
        if now <= authorization.valid_after or now >= authorization.valid_before:
            raise CommercialX402Error("x402-authorization-not-current")

        try:
            verified = self.facilitator.verify(payload, requirement.wire())
            assert_verify_response(verified, payer=authorization.from_address)
        except X402Error as exc:
            raise CommercialX402Error(str(exc)) from exc
        except Exception as exc:
            raise CommercialX402Error("x402-facilitator-verify-unavailable") from exc
        self.x402_journal.transition(execution_id, "VERIFIED")

        capsule, offers, plan, selected, grant, explanation = reconstruct_commercial_context(
            self.commercial_journal, record.grant_id, now=now
        )
        self.x402_journal.transition(execution_id, "RESOURCE_DISPATCHED")
        dispatch_id = "action:x402:" + canonical_hash({
            "grant": grant.digest,
            "authorization": authorization.digest,
            "payload": context["capability_payload_digest"],
        })[:28]
        try:
            reference = execute_reference_capability(
                grant,
                context["capability_payload"],
                action_id=dispatch_id,
            )
        except Exception as exc:
            self.x402_journal.transition(execution_id, "IN_DOUBT")
            commercial = self.commercial_journal.get(record.grant_id)
            if commercial.state == "APPROVED":
                self.commercial_journal.mark_in_doubt(record.grant_id)
            raise CommercialX402Error("x402-resource-execution-in-doubt") from exc
        self.x402_journal.transition(execution_id, "RESOURCE_EXECUTED")
        context["payment_payload"] = payload
        context["verify_response"] = verified
        context["dispatch_id"] = dispatch_id
        context["artifact"] = reference.artifact
        context["reference_action_receipt"] = reference.action_receipt
        self.x402_journal.replace_context(execution_id, context)

        self.x402_journal.transition(execution_id, "SETTLEMENT_PENDING")
        try:
            settled = self.facilitator.settle(payload, requirement.wire())
            tx_hash = settlement_transaction(
                settled,
                payer=authorization.from_address,
                network=requirement.network,
            )
        except X402Error as exc:
            text = str(exc)
            if text.startswith("x402-settlement-pending:"):
                tx_hash = text.partition(":")[2]
                self.x402_journal.transition(execution_id, "IN_DOUBT", transaction_hash=tx_hash)
                commercial = self.commercial_journal.get(record.grant_id)
                if commercial.state == "APPROVED":
                    self.commercial_journal.mark_in_doubt(record.grant_id)
                return {
                    "environment": "LIVE",
                    "rail": "x402-v2-exact-eip3009",
                    "status": "IN_DOUBT",
                    "execution_id": execution_id,
                    "transaction_hash": tx_hash,
                    "retry": "reconcile-only",
                }
            self.x402_journal.transition(execution_id, "IN_DOUBT")
            commercial = self.commercial_journal.get(record.grant_id)
            if commercial.state == "APPROVED":
                self.commercial_journal.mark_in_doubt(record.grant_id)
            raise CommercialX402Error(text) from exc
        except Exception as exc:
            self.x402_journal.transition(execution_id, "IN_DOUBT")
            commercial = self.commercial_journal.get(record.grant_id)
            if commercial.state == "APPROVED":
                self.commercial_journal.mark_in_doubt(record.grant_id)
            raise CommercialX402Error("x402-settlement-uncertain") from exc

        self.x402_journal.transition(execution_id, "SETTLED", transaction_hash=tx_hash)
        return self._observe_and_finalize(execution_id, now=now)

    def reconcile(self, execution_id: str, *, now: int) -> dict[str, Any]:
        record = self.x402_journal.get(execution_id)
        if record.state not in {"SETTLED", "IN_DOUBT"}:
            raise CommercialX402Error(f"x402-reconcile-not-allowed:{record.state}")
        if not record.transaction_hash:
            raise CommercialX402Error("x402-reconcile-transaction-unknown")
        return self._observe_and_finalize(execution_id, now=now)

    def _observe_and_finalize(self, execution_id: str, *, now: int) -> dict[str, Any]:
        record = self.x402_journal.get(execution_id)
        context = self.x402_journal.context(execution_id)
        route, requirement, authorization = self._validate_context(execution_id, context)
        if not record.transaction_hash:
            raise CommercialX402Error("x402-observation-transaction-missing")
        try:
            settlement = observe_eip3009_settlement(
                self.rpc, record.transaction_hash, requirement, authorization
            )
        except SettlementError as exc:
            if record.state == "SETTLED":
                self.x402_journal.transition(execution_id, "IN_DOUBT")
            commercial = self.commercial_journal.get(record.grant_id)
            if commercial.state == "APPROVED":
                self.commercial_journal.mark_in_doubt(record.grant_id)
            raise CommercialX402Error("x402-settlement-not-observed") from exc

        current = self.x402_journal.get(execution_id)
        if current.state in {"SETTLED", "IN_DOUBT"}:
            self.x402_journal.transition(execution_id, "OBSERVED")
        else:
            raise CommercialX402Error(f"x402-observation-not-allowed:{current.state}")

        capsule, offers, plan, selected, grant, explanation = reconstruct_commercial_context(
            self.commercial_journal, record.grant_id, now=now
        )
        reference = ReferenceCapabilityResult(
            context["dispatch_id"],
            context["reference_action_receipt"],
            context["artifact"],
        )
        paid_receipt = {
            "schema": "agentpay-x402-paid-capability-receipt/1",
            "action_id": context["dispatch_id"],
            "grant_digest": grant.digest,
            "route_digest": route.digest,
            "provider_id": grant.provider_id,
            "provider_binding_digest": route.provider_binding_digest,
            "provider_admission_digest": route.provider_admission_digest,
            "capability": grant.capability,
            "x402_requirement_digest": requirement.digest,
            "eip3009_authorization_digest": authorization.digest,
            "eip3009_nonce": authorization.nonce,
            "settlement_digest": settlement.digest,
            "artifact_digest": canonical_hash(reference.artifact),
            "execution_receipt_digest": canonical_hash(reference.action_receipt),
            "evidence": sorted(set(reference.action_receipt.get("evidence", [])) | {
                "settlement_observation", "eip3009-authorization-used-observation"
            }),
        }
        paid_receipt["action_proof_hash"] = canonical_hash(paid_receipt)
        paid_result = ReferenceCapabilityResult(
            context["dispatch_id"], paid_receipt, reference.artifact
        )
        assessment = assess_reference_outcome(capsule, grant, paid_result, now=now)
        if assessment.verdict != "PASS":
            raise CommercialX402Error("x402-commercial-outcome-not-satisfied")

        commercial = self.commercial_journal.get(record.grant_id)
        if commercial.state in {"APPROVED", "IN_DOUBT"}:
            self.commercial_journal.mark_dispatched(record.grant_id, context["dispatch_id"])
        self.commercial_journal.mark_observed(
            record.grant_id,
            action_id=context["dispatch_id"],
            action_proof_hash=paid_receipt["action_proof_hash"],
        )
        proof = make_commercial_proof(
            capsule,
            plan,
            authority_digest=grant.digest,
            action_proof_hash=paid_receipt["action_proof_hash"],
            outcome=assessment.reason,
            observed_at=now,
        )
        verification = verify_commercial_bundle(
            capsule=capsule,
            plan=plan,
            offer=selected,
            grant=grant,
            action_receipt=paid_receipt,
            artifact=reference.artifact,
            assessment=assessment,
            proof=proof,
        )
        if verification["verdict"] != "VERIFIED":
            raise CommercialX402Error("x402-commercial-proof-verification-failed")
        self.commercial_journal.consume(record.grant_id)
        self.x402_journal.transition(execution_id, "CONSUMED")
        return {
            "environment": "LIVE",
            "rail": "x402-v2-exact-eip3009",
            "status": "VERIFIED",
            "commercial_state": "CONSUMED",
            "x402_state": "CONSUMED",
            "settlement": {**asdict(settlement), "digest": settlement.digest},
            "action_receipt": paid_receipt,
            "artifact": reference.artifact,
            "outcome_assessment": {**asdict(assessment), "digest": assessment.digest},
            "commercial_proof": proof,
            "verification": verification,
        }
