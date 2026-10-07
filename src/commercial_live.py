from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

from src.commercial import CapabilityOffer, CommercialIntentCapsule, CommercialPlan, make_commercial_proof
from src.commercial_execution import (
    CommercialExecutionError,
    CommercialExecutionJournal,
    CommercialGrant,
    ReferenceCapabilityResult,
    assess_reference_outcome,
    execute_reference_capability,
    project_commercial_grant,
    reconstruct_commercial_context,
    validate_reference_payload,
    verify_commercial_bundle,
)
from src.execution import ExecutionJournal, ExecutionStateError
from src.live import LiveConfig
from src.model import Authority, Intent, Quote, canonical_hash, decide
from src.settlement import JsonRpcClient, SettlementError, transaction_request


class CommercialLiveError(RuntimeError):
    pass


def _address(value: str) -> str:
    value = str(value).strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise CommercialLiveError("commercial-route-address-invalid")
    int(value[2:], 16)
    return value


@dataclass(frozen=True)
class CapabilityRoute:
    route_id: str
    offer_digest: str
    provider_id: str
    capability: str
    adapter_id: str
    request_schema: str
    observation_schema: str
    payment_chain_id: int
    payment_asset_contract: str
    payment_recipient: str
    payment_amount_atomic: int
    expires_at: int

    def __post_init__(self) -> None:
        for field_name, code in (
            ("route_id", "route-id-required"),
            ("offer_digest", "route-offer-digest-required"),
            ("provider_id", "route-provider-required"),
            ("capability", "route-capability-required"),
            ("adapter_id", "route-adapter-required"),
            ("request_schema", "route-request-schema-required"),
            ("observation_schema", "route-observation-schema-required"),
        ):
            if not str(getattr(self, field_name)).strip():
                raise CommercialLiveError(code)
        if self.payment_chain_id <= 0:
            raise CommercialLiveError("route-chain-invalid")
        object.__setattr__(self, "payment_asset_contract", _address(self.payment_asset_contract))
        object.__setattr__(self, "payment_recipient", _address(self.payment_recipient))
        if self.payment_amount_atomic <= 0:
            raise CommercialLiveError("route-amount-invalid")
        if self.expires_at <= 0:
            raise CommercialLiveError("route-expiry-invalid")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": "agentpay-capability-route/1", **asdict(self)})


def build_reference_paid_route(
    grant: CommercialGrant,
    offer: CapabilityOffer,
    config: LiveConfig,
    *,
    now: int,
) -> CapabilityRoute:
    if grant.provider_id != "provider:render-only":
        raise CommercialLiveError("provider-route-not-configured")
    if grant.capability != "browser.render.verify":
        raise CommercialLiveError("capability-route-not-configured")
    if offer.digest != grant.offer_digest:
        raise CommercialLiveError("route-offer-binding-mismatch")
    if grant.settlement_asset != "USDC":
        raise CommercialLiveError("route-settlement-asset-unsupported")
    if grant.exact_price_atomic <= 0:
        raise CommercialLiveError("route-payment-not-required")
    if grant.exact_price_atomic > config.maximum_amount_atomic:
        raise CommercialLiveError("route-price-exceeds-live-authority")

    expires_at = min(grant.expires_at, offer.expires_at, now + 300)
    route_body = {
        "offer_digest": offer.digest,
        "provider_id": grant.provider_id,
        "capability": grant.capability,
        "adapter_id": "reference.browser-render.verify/1",
        "request_schema": "agentpay-render-verify-request/1",
        "observation_schema": "agentpay-render-verify-observation/1",
        "payment_chain_id": config.chain_id,
        "payment_asset_contract": _address(config.asset_contract),
        "payment_recipient": _address(config.recipient),
        "payment_amount_atomic": grant.exact_price_atomic,
        "expires_at": expires_at,
    }
    route_id = "route:" + canonical_hash(route_body)[:32]
    return CapabilityRoute(route_id=route_id, **route_body)


def _payment_identity(
    grant: CommercialGrant,
    route: CapabilityRoute,
    payload: dict[str, Any],
) -> tuple[str, str, str]:
    payload_digest = canonical_hash(payload)
    binding = {
        "grant_digest": grant.digest,
        "route_digest": route.digest,
        "payload_digest": payload_digest,
    }
    digest = canonical_hash(binding)
    return (
        "commercial-intent:" + digest[:24],
        "commercial-quote:" + digest[:24],
        "commercial-decision:" + digest[:24],
    )


class PaidCommercialCoordinator:
    """Connect one exact Commercial Grant to the existing external-wallet rail.

    This coordinator never signs or broadcasts a transaction. It prepares the
    exact ERC-20 transfer, persists payment authority before wallet handoff,
    and later reconstructs settlement independently from Base RPC before any
    capability result can become a Commercial Proof.
    """

    def __init__(
        self,
        *,
        commercial_journal: CommercialExecutionJournal,
        payment_journal: ExecutionJournal,
        live_config: LiveConfig,
        rpc: JsonRpcClient | None = None,
    ):
        self.commercial_journal = commercial_journal
        self.payment_journal = payment_journal
        self.live_config = live_config.validate()
        self.rpc = rpc or JsonRpcClient(self.live_config.rpc_url)

    def prepare_wallet(
        self,
        grant_id: str,
        *,
        commercial_approval_digest: str,
        payload: dict[str, Any],
        now: int,
    ) -> dict[str, Any]:
        capsule, offers, plan, selected, grant, explanation = reconstruct_commercial_context(
            self.commercial_journal,
            grant_id,
            now=now,
        )
        if now > grant.expires_at:
            raise CommercialLiveError("commercial-grant-expired")
        validate_reference_payload(grant, payload)

        route = build_reference_paid_route(grant, selected, self.live_config, now=now)
        if route.payment_amount_atomic != grant.exact_price_atomic:
            raise CommercialLiveError("route-price-binding-mismatch")
        if route.payment_chain_id != self.live_config.chain_id:
            raise CommercialLiveError("route-chain-binding-mismatch")
        if route.payment_asset_contract != _address(self.live_config.asset_contract):
            raise CommercialLiveError("route-asset-binding-mismatch")

        record = self.commercial_journal.get(grant_id)
        if record.state == "PREPARED":
            self.commercial_journal.approve(grant_id, commercial_approval_digest)
        elif record.state != "APPROVED":
            raise CommercialLiveError(f"commercial-wallet-prepare-not-allowed:{record.state}")

        intent_id, quote_id, decision_id = _payment_identity(grant, route, payload)
        request_digest = canonical_hash({
            "grant_digest": grant.digest,
            "route_digest": route.digest,
            "payload_digest": canonical_hash(payload),
        })
        service_id = "capability:" + grant.capability
        expires_at = min(grant.expires_at, route.expires_at)

        quote = Quote(
            quote_id=quote_id,
            service_id=service_id,
            recipient=route.payment_recipient,
            chain_id=route.payment_chain_id,
            asset_contract=route.payment_asset_contract,
            amount_atomic=route.payment_amount_atomic,
            expires_at=expires_at,
            request_digest=request_digest,
        )
        intent = Intent(
            intent_id=intent_id,
            agent_id=capsule.principal_id,
            service_id=service_id,
            request_digest=request_digest,
            created_at=now,
        )
        authority = decide(
            intent,
            quote,
            decision_id=decision_id,
            maximum_amount_atomic=grant.exact_price_atomic,
            recipient=route.payment_recipient,
            service_id=service_id,
            chain_id=route.payment_chain_id,
            asset_contract=route.payment_asset_contract,
            expires_at=expires_at,
            now=now,
        )
        if authority.decision != "PERMIT":
            raise CommercialLiveError("commercial-payment-authority-denied")

        tx = transaction_request(authority, quote, now=now)
        context = {
            "grant_id": grant.grant_id,
            "grant_digest": grant.digest,
            "route": asdict(route),
            "route_digest": route.digest,
            "payload": payload,
            "payload_digest": canonical_hash(payload),
            "intent": asdict(intent),
            "quote": asdict(quote),
            "authority": asdict(authority),
            "transaction": tx,
            "commercial_explanation_digest": canonical_hash(explanation),
        }
        context_json = json.dumps(context, sort_keys=True, separators=(",", ":"))

        try:
            self.payment_journal.reserve(authority, quote, context_json=context_json)
        except ExecutionStateError as exc:
            if str(exc) != "authority-already-reserved":
                raise
            existing = self.payment_journal.get(decision_id)
            if existing.state != "PREPARED":
                raise CommercialLiveError(
                    f"commercial-payment-already-progressed:{existing.state}"
                ) from exc
            if self.payment_journal.context(decision_id) != context_json:
                raise CommercialLiveError("commercial-payment-context-mismatch") from exc

        return {
            "environment": "LIVE",
            "status": "AWAITING_WALLET",
            "grant_id": grant.grant_id,
            "grant_digest": grant.digest,
            "route": {**asdict(route), "digest": route.digest},
            "payment_decision_id": decision_id,
            "payment_authority": {**asdict(authority), "digest": authority.digest},
            "quote": {**asdict(quote), "digest": quote.digest},
            "wallet_request": {
                "chainId": hex(tx["chain_id"]),
                "to": tx["to"],
                "value": hex(tx["value"]),
                "data": tx["data"],
            },
            "hio": {
                "provider_id": grant.provider_id,
                "capability": grant.capability,
                "amount_atomic": route.payment_amount_atomic,
                "asset": grant.settlement_asset,
                "chain_id": route.payment_chain_id,
                "recipient": route.payment_recipient,
                "disclosures": list(grant.disclosures),
                "retention_seconds": grant.retention_seconds,
                "credential_ttl_seconds": grant.credential_ttl_seconds,
                "requires_wallet_approval": True,
            },
        }

    def abort_wallet(self, grant_id: str, decision_id: str) -> dict[str, Any]:
        payment = self.payment_journal.get(decision_id)
        if payment.state != "PREPARED":
            raise CommercialLiveError(f"wallet-abort-not-allowed:{payment.state}")
        context = json.loads(self.payment_journal.context(decision_id) or "{}")
        if context.get("grant_id") != grant_id:
            raise CommercialLiveError("wallet-grant-binding-mismatch")
        self.payment_journal.abort_prepared(decision_id)
        commercial = self.commercial_journal.get(grant_id)
        if commercial.state == "APPROVED":
            self.commercial_journal.abort(grant_id)
        return {
            "environment": "LIVE",
            "grant_id": grant_id,
            "payment_decision_id": decision_id,
            "state": "ABORTED",
        }

    def mark_wallet_uncertain(self, grant_id: str, decision_id: str) -> dict[str, Any]:
        context = json.loads(self.payment_journal.context(decision_id) or "{}")
        if context.get("grant_id") != grant_id:
            raise CommercialLiveError("wallet-grant-binding-mismatch")
        payment = self.payment_journal.get(decision_id)
        if payment.state == "PREPARED":
            payment = self.payment_journal.mark_in_doubt(decision_id)
        commercial = self.commercial_journal.get(grant_id)
        if commercial.state == "APPROVED":
            commercial = self.commercial_journal.mark_in_doubt(grant_id)
        return {
            "environment": "LIVE",
            "grant_id": grant_id,
            "payment_decision_id": decision_id,
            "payment_state": payment.state,
            "commercial_state": commercial.state,
        }

    def reconcile(
        self,
        grant_id: str,
        decision_id: str,
        tx_hash: str,
        sender: str,
        *,
        now: int,
    ) -> dict[str, Any]:
        if not isinstance(tx_hash, str) or not tx_hash.startswith("0x") or len(tx_hash) < 10:
            raise CommercialLiveError("transaction-hash-invalid")
        sender = _address(sender)

        raw_context = self.payment_journal.context(decision_id)
        if not raw_context:
            raise CommercialLiveError("commercial-payment-context-missing")
        context = json.loads(raw_context)
        if context.get("grant_id") != grant_id:
            raise CommercialLiveError("wallet-grant-binding-mismatch")

        capsule, offers, plan, selected, grant, explanation = reconstruct_commercial_context(
            self.commercial_journal,
            grant_id,
            now=now,
        )
        route = CapabilityRoute(**context["route"])
        if context.get("grant_digest") != grant.digest:
            raise CommercialLiveError("payment-grant-digest-mismatch")
        if context.get("route_digest") != route.digest:
            raise CommercialLiveError("payment-route-digest-mismatch")
        if route.offer_digest != selected.digest:
            raise CommercialLiveError("payment-offer-digest-mismatch")
        if route.provider_id != grant.provider_id or route.capability != grant.capability:
            raise CommercialLiveError("payment-route-scope-mismatch")
        if context.get("payload_digest") != canonical_hash(context.get("payload")):
            raise CommercialLiveError("payment-payload-digest-mismatch")

        intent = Intent(**context["intent"])
        quote = Quote(**context["quote"])
        authority = Authority(**context["authority"])
        expected_tx = transaction_request(
            authority,
            quote,
            now=min(intent.created_at, authority.expires_at, quote.expires_at),
        )
        if context.get("transaction") != expected_tx:
            raise CommercialLiveError("commercial-payment-transaction-corrupt")

        payment = self.payment_journal.get(decision_id)
        if payment.state == "PREPARED":
            self.payment_journal.mark_dispatched(decision_id, tx_hash)
        elif payment.state == "IN_DOUBT" and not payment.transaction_hash:
            self.payment_journal.mark_dispatched(decision_id, tx_hash)
        elif payment.state in {"IN_DOUBT", "DISPATCHED"} and payment.transaction_hash == tx_hash:
            pass
        else:
            raise CommercialLiveError(f"payment-reconciliation-not-allowed:{payment.state}")

        try:
            settlement = self.rpc.observe(tx_hash, quote, sender)
        except SettlementError as exc:
            current = self.payment_journal.get(decision_id)
            if current.state == "DISPATCHED":
                self.payment_journal.mark_in_doubt(decision_id, tx_hash)
            commercial = self.commercial_journal.get(grant_id)
            if commercial.state == "APPROVED":
                self.commercial_journal.mark_in_doubt(grant_id)
            raise CommercialLiveError("commercial-settlement-not-observed") from exc

        current = self.payment_journal.get(decision_id)
        if current.state in {"DISPATCHED", "IN_DOUBT"}:
            self.payment_journal.mark_observed(decision_id, tx_hash)
        else:
            raise CommercialLiveError(f"payment-observation-not-allowed:{current.state}")
        self.payment_journal.consume(decision_id)

        payload = context["payload"]
        validate_reference_payload(grant, payload)
        dispatch_id = "action:" + canonical_hash({
            "grant_digest": grant.digest,
            "route_digest": route.digest,
            "payload_digest": context["payload_digest"],
            "settlement_digest": settlement.digest,
        })[:32]

        commercial = self.commercial_journal.get(grant_id)
        if commercial.state in {"APPROVED", "IN_DOUBT"}:
            self.commercial_journal.mark_dispatched(grant_id, dispatch_id)
        elif commercial.state != "DISPATCHED" or commercial.action_id != dispatch_id:
            raise CommercialLiveError(
                f"commercial-dispatch-not-allowed:{commercial.state}"
            )

        try:
            reference = execute_reference_capability(
                grant,
                payload,
                action_id=dispatch_id,
            )
        except Exception as exc:
            current = self.commercial_journal.get(grant_id)
            if current.state == "DISPATCHED":
                self.commercial_journal.mark_in_doubt(grant_id, dispatch_id)
            raise CommercialLiveError("capability-execution-in-doubt") from exc

        paid_receipt = {
            "schema": "agentpay-paid-capability-receipt/1",
            "action_id": dispatch_id,
            "grant_digest": grant.digest,
            "route_digest": route.digest,
            "provider_id": grant.provider_id,
            "capability": grant.capability,
            "payment_authority_digest": authority.digest,
            "quote_digest": quote.digest,
            "settlement_digest": settlement.digest,
            "artifact_digest": canonical_hash(reference.artifact),
            "execution_receipt_digest": canonical_hash(reference.action_receipt),
            "evidence": sorted(set(reference.action_receipt.get("evidence", [])) | {"settlement_observation"}),
        }
        paid_receipt["action_proof_hash"] = canonical_hash(paid_receipt)
        paid_result = ReferenceCapabilityResult(
            dispatch_id,
            paid_receipt,
            reference.artifact,
        )

        assessment = assess_reference_outcome(
            capsule,
            grant,
            paid_result,
            now=now,
        )
        if assessment.verdict != "PASS":
            self.commercial_journal.mark_in_doubt(grant_id, dispatch_id)
            raise CommercialLiveError("commercial-outcome-not-satisfied")

        self.commercial_journal.mark_observed(
            grant_id,
            action_id=dispatch_id,
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
            raise CommercialLiveError("commercial-paid-bundle-verification-failed")

        self.commercial_journal.consume(grant_id)
        return {
            "environment": "LIVE",
            "status": "VERIFIED",
            "commercial_state": "CONSUMED",
            "payment_state": "CONSUMED",
            "settlement": {**asdict(settlement), "digest": settlement.digest},
            "route": {**asdict(route), "digest": route.digest},
            "action_receipt": paid_receipt,
            "artifact": reference.artifact,
            "outcome_assessment": {**asdict(assessment), "digest": assessment.digest},
            "commercial_proof": proof,
            "verification": verification,
        }
