import os
import tempfile
import unittest
from unittest.mock import patch

from src.commercial_demo import release_validation_objects
from src.commercial_execution import CommercialCoordinator, CommercialExecutionJournal
from src.commercial_x402 import CommercialX402Coordinator, CommercialX402Error, X402ExecutionJournal
from src.live import LiveConfig
from src.facilitator_admission import FacilitatorBinding, FacilitatorRegistry, FacilitatorTransportProof
from src.provider_admission import ProviderBinding, ProviderRegistry
from src.settlement import TRANSFER_TOPIC
from src.x402 import AUTHORIZATION_USED_TOPIC, EIP3009Authorization, TRANSFER_WITH_AUTHORIZATION_SELECTOR

TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
PAYEE = "0x000000000000000000000000000000000000beef"
PAYER = "0x000000000000000000000000000000000000cafe"
RESOURCE = "https://provider.example/v1/render-verify"
NOW = 1_800_000_000
TX = "0x" + "12" * 32
SIG = "0x" + "11" * 65
FACILITATOR_ID = "facilitator:test"
VERIFY_URL = "https://facilitator.example/verify"
SETTLE_URL = "https://facilitator.example/settle"
TLS_PIN = "sha256:test-spki"


def transfer_with_authorization_input(authorization):
    def address_word(value):
        return value[2:].lower().rjust(64, "0")
    def int_word(value):
        return hex(int(value))[2:].rjust(64, "0")
    return TRANSFER_WITH_AUTHORIZATION_SELECTOR + "".join((
        address_word(authorization.from_address),
        address_word(authorization.to),
        int_word(authorization.value),
        int_word(authorization.valid_after),
        int_word(authorization.valid_before),
        authorization.nonce[2:].lower(),
        int_word(27),
        "11" * 32,
        "22" * 32,
    ))


def topic_address(address):
    return "0x" + address[2:].lower().rjust(64, "0")


def provider_registry():
    binding = ProviderBinding(
        provider_id="provider:render-only",
        legal_identity="External Test Provider Ltd.",
        capability="browser.render.verify",
        adapter_id=RESOURCE,
        request_schema="agentpay-render-verify-request/1",
        response_schema="agentpay-render-verify-result/1",
        observation_schema="agentpay-render-verify-observation/1",
        payment_recipient=PAYEE,
        settlement_asset="USDC",
        allowed_disclosures=("rendered_page",),
        maximum_retention_seconds=0,
        evidence_types=("execution_receipt", "result_observation", "settlement_observation"),
        idempotency_model="idempotency-key-required",
        cancellation_model="cancel-before-dispatch",
        observation_model="signed-result-plus-independent-fetch",
        jurisdiction="CA",
        valid_from=NOW - 60,
        valid_until=NOW + 3600,
        version=1,
    )
    registry = ProviderRegistry()
    assert registry.admit(binding, now=NOW).decision == "ADMIT"
    return registry


def facilitator_registry():
    binding = FacilitatorBinding(
        facilitator_id=FACILITATOR_ID,
        legal_identity="External Test Facilitator Ltd.",
        verify_url=VERIFY_URL,
        settle_url=SETTLE_URL,
        schemes=("exact",),
        networks=("eip155:8453",),
        asset_contracts=(TOKEN,),
        dns_names=("facilitator.example",),
        tls_spki_sha256=(TLS_PIN,),
        transport="https-json",
        valid_from=NOW - 60,
        valid_until=NOW + 3600,
        version=1,
    )
    proof = FacilitatorTransportProof(
        facilitator_id=FACILITATOR_ID,
        verify_url=VERIFY_URL,
        settle_url=SETTLE_URL,
        resolved_host="facilitator.example",
        tls_spki_sha256=TLS_PIN,
        verify_behavior="verification-only",
        settle_behavior="settlement-only",
        independent_probe=True,
        observed_at=NOW - 30,
        valid_until=NOW + 600,
    )
    registry = FacilitatorRegistry()
    assert registry.admit(binding, proof, now=NOW).decision == "ADMIT"
    return registry


def payment_required(amount="30000", extensions=None):
    document = {
        "x402Version": 2,
        "resource": {"url": RESOURCE, "description": "render verify", "mimeType": "application/json"},
        "accepts": [{
            "scheme": "exact",
            "network": "eip155:8453",
            "amount": amount,
            "asset": TOKEN,
            "payTo": PAYEE,
            "maxTimeoutSeconds": 60,
            "extra": {
                "assetTransferMethod": "eip3009",
                "paymentFlow": "authorization",
                "name": "USD Coin",
                "version": "2",
            },
        }],
    }
    if extensions is not None:
        document["extensions"] = extensions
    return document


class FakeFacilitator:
    facilitator_id = FACILITATOR_ID
    verify_url = VERIFY_URL
    settle_url = SETTLE_URL
    tls_spki_sha256 = TLS_PIN

    def __init__(self, verify_valid=True, settle_mode="success"):
        self.verify_valid = verify_valid
        self.settle_mode = settle_mode
        self.calls = []
        self.last_verify_payload = None

    def verify(self, payload, requirement):
        self.calls.append("verify")
        self.last_verify_payload = payload
        if self.verify_valid:
            return {"isValid": True, "payer": PAYER}
        return {"isValid": False, "invalidReason": "invalid_exact_evm_payload_signature", "payer": PAYER}

    def settle(self, payload, requirement):
        self.calls.append("settle")
        if self.settle_mode == "success":
            return {"success": True, "transaction": TX, "network": "eip155:8453", "payer": PAYER}
        if self.settle_mode == "pending":
            return {"success": False, "errorReason": "settlement_pending", "transaction": TX, "network": "eip155:8453", "payer": PAYER}
        return {"success": False, "errorReason": "invalid_transaction_state", "transaction": "", "network": "eip155:8453", "payer": PAYER}


class FakeRpc:
    def __init__(self, journal, execution_id):
        self.journal = journal
        self.execution_id = execution_id

    def call(self, method, params):
        if method == "eth_chainId":
            return hex(8453)
        if method == "eth_getTransactionByHash":
            authorization = EIP3009Authorization(**self.journal.context(self.execution_id)["authorization"])
            return {
                "hash": TX,
                "to": TOKEN,
                "from": "0x0000000000000000000000000000000000001111",
                "input": transfer_with_authorization_input(authorization),
            }
        if method == "eth_getTransactionReceipt":
            nonce = self.journal.context(self.execution_id)["authorization"]["nonce"]
            return {
                "status": "0x1",
                "transactionHash": TX,
                "logs": [
                    {"address": TOKEN, "topics": [AUTHORIZATION_USED_TOPIC, topic_address(PAYER), nonce], "data": "0x"},
                    {"address": TOKEN, "topics": [TRANSFER_TOPIC, topic_address(PAYER), topic_address(PAYEE)], "data": hex(30000)},
                ],
            }
        raise AssertionError(method)


class CommercialX402Tests(unittest.TestCase):
    def setUp(self):
        fd, self.commercial_path = tempfile.mkstemp(); os.close(fd); os.unlink(self.commercial_path)
        fd, self.x402_path = tempfile.mkstemp(); os.close(fd); os.unlink(self.x402_path)
        self.commercial_journal = CommercialExecutionJournal(self.commercial_path)
        self.x402_journal = X402ExecutionJournal(self.x402_path)
        self.commercial = CommercialCoordinator(self.commercial_journal)
        self.registry = provider_registry()
        self.facilitator_registry = facilitator_registry()
        self.config = LiveConfig(
            rpc_url="https://rpc.example",
            journal_path="unused.sqlite3",
            chain_id=8453,
            asset_contract=TOKEN,
            recipient=PAYEE,
            maximum_amount_atomic=1_000_000,
        )
        self.capsule, self.offers = release_validation_objects(now=NOW)
        self.prepared = self.commercial.prepare(self.capsule, self.offers, now=NOW)
        self.capability_payload = {
            "rendered_page_digest": "rendered:test",
            "reference_digest": "reference:approved-v6",
        }

    def tearDown(self):
        for path in (self.commercial_path, self.x402_path):
            if os.path.exists(path):
                os.unlink(path)

    def coordinator(self, facilitator=None):
        facilitator = facilitator or FakeFacilitator()
        return CommercialX402Coordinator(
            commercial_journal=self.commercial_journal,
            x402_journal=self.x402_journal,
            live_config=self.config,
            provider_registry=self.registry,
            facilitator=facilitator,
            facilitator_registry=self.facilitator_registry,
            facilitator_id=FACILITATOR_ID,
            rpc=None,
        ), facilitator

    def prepare_x402(self, coordinator):
        return coordinator.prepare(
            self.prepared["grant"]["grant_id"],
            commercial_approval_digest=self.prepared["approval_digest"],
            capability_payload=self.capability_payload,
            payment_required=payment_required(),
            payer=PAYER,
            now=NOW + 1,
        )

    def test_unadmitted_facilitator_blocks_before_authorization(self):
        self.facilitator_registry.revoke(FACILITATOR_ID)
        coordinator, facilitator = self.coordinator()
        with self.assertRaisesRegex(CommercialX402Error, "facilitator-not-admitted"):
            self.prepare_x402(coordinator)
        self.assertEqual(facilitator.calls, [])

    def test_facilitator_runtime_endpoint_substitution_fails_closed(self):
        facilitator = FakeFacilitator()
        facilitator.verify_url = "https://evil.example/verify"
        coordinator, _ = self.coordinator(facilitator)
        with self.assertRaisesRegex(CommercialX402Error, "x402-facilitator-runtime-binding-mismatch"):
            self.prepare_x402(coordinator)

    def test_facilitator_revocation_after_signature_release_blocks_verify(self):
        facilitator = FakeFacilitator()
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        coordinator.confirm(out["execution_id"], execution_approval_digest=out["execution_approval_digest"], now=NOW + 2)
        self.facilitator_registry.revoke(FACILITATOR_ID)
        with self.assertRaisesRegex(CommercialX402Error, "facilitator-not-admitted"):
            coordinator.submit_signature_and_execute(out["execution_id"], signature=SIG, now=NOW + 3)
        self.assertEqual(facilitator.calls, [])

    def test_prepare_is_bounded_and_idempotent(self):
        coordinator, _ = self.coordinator()
        first = self.prepare_x402(coordinator)
        second = self.prepare_x402(coordinator)
        self.assertEqual(first["status"], "AWAITING_EXECUTION_APPROVAL")
        self.assertIsNone(first["wallet_request"])
        self.assertEqual(first["execution_id"], second["execution_id"])
        self.assertEqual(first["authorization"]["nonce"], second["authorization"]["nonce"])
        self.assertEqual(self.commercial_journal.get(self.prepared["grant"]["grant_id"]).state, "PREPARED")

    def test_confirm_releases_typed_signature_only(self):
        coordinator, _ = self.coordinator()
        out = self.prepare_x402(coordinator)
        confirmed = coordinator.confirm(
            out["execution_id"],
            execution_approval_digest=out["execution_approval_digest"],
            now=NOW + 2,
        )
        self.assertEqual(confirmed["status"], "AWAITING_WALLET_SIGNATURE")
        self.assertEqual(confirmed["wallet_request"]["method"], "eth_signTypedData_v4")
        self.assertEqual(self.x402_journal.get(out["execution_id"]).state, "SIGNING")

    def test_revocation_before_signature_release_fails_closed(self):
        coordinator, _ = self.coordinator()
        out = self.prepare_x402(coordinator)
        self.registry.revoke("provider:render-only")
        with self.assertRaisesRegex(CommercialX402Error, "provider-not-admitted"):
            coordinator.confirm(
                out["execution_id"],
                execution_approval_digest=out["execution_approval_digest"],
                now=NOW + 2,
            )

    def test_revocation_after_signature_release_but_before_resource_blocks_execution(self):
        facilitator = FakeFacilitator()
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        coordinator.confirm(
            out["execution_id"],
            execution_approval_digest=out["execution_approval_digest"],
            now=NOW + 2,
        )
        self.registry.revoke("provider:render-only")
        with self.assertRaisesRegex(CommercialX402Error, "provider-not-admitted"):
            coordinator.submit_signature_and_execute(out["execution_id"], signature=SIG, now=NOW + 3)
        self.assertEqual(facilitator.calls, [])
        self.assertEqual(self.x402_journal.get(out["execution_id"]).state, "SIGNING")

    def test_context_tamper_is_detected_before_signature_processing(self):
        facilitator = FakeFacilitator()
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        execution_id = out["execution_id"]
        coordinator.confirm(execution_id, execution_approval_digest=out["execution_approval_digest"], now=NOW + 2)
        context = self.x402_journal.context(execution_id)
        context["capability_payload"]["reference_digest"] = "reference:tampered"
        self.x402_journal.replace_context(execution_id, context)
        with self.assertRaisesRegex(CommercialX402Error, "x402-capability-payload-context-mismatch"):
            coordinator.submit_signature_and_execute(execution_id, signature=SIG, now=NOW + 3)
        self.assertEqual(facilitator.calls, [])

    def test_invalid_facilitator_verification_never_settles(self):
        facilitator = FakeFacilitator(verify_valid=False)
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        coordinator.confirm(out["execution_id"], execution_approval_digest=out["execution_approval_digest"], now=NOW + 2)
        with self.assertRaisesRegex(CommercialX402Error, "x402-facilitator-verification-failed"):
            coordinator.submit_signature_and_execute(out["execution_id"], signature=SIG, now=NOW + 3)
        self.assertEqual(facilitator.calls, ["verify"])
        self.assertEqual(self.x402_journal.get(out["execution_id"]).state, "SIGNING")

    def test_resource_failure_never_calls_settlement(self):
        facilitator = FakeFacilitator()
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        execution_id = out["execution_id"]
        coordinator.confirm(execution_id, execution_approval_digest=out["execution_approval_digest"], now=NOW + 2)
        with patch("src.commercial_x402.execute_reference_capability", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(CommercialX402Error, "x402-resource-execution-in-doubt"):
                coordinator.submit_signature_and_execute(execution_id, signature=SIG, now=NOW + 3)
        self.assertEqual(facilitator.calls, ["verify"])
        self.assertEqual(self.x402_journal.get(execution_id).state, "IN_DOUBT")

    def test_expired_authorization_never_reaches_facilitator(self):
        facilitator = FakeFacilitator()
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        execution_id = out["execution_id"]
        coordinator.confirm(execution_id, execution_approval_digest=out["execution_approval_digest"], now=NOW + 2)
        expires = int(out["authorization"]["valid_before"])
        with self.assertRaisesRegex(CommercialX402Error, "x402-authorization-not-current"):
            coordinator.submit_signature_and_execute(execution_id, signature=SIG, now=expires)
        self.assertEqual(facilitator.calls, [])

    def test_happy_path_verify_resource_settle_observe_and_prove(self):
        facilitator = FakeFacilitator()
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        execution_id = out["execution_id"]
        coordinator.confirm(execution_id, execution_approval_digest=out["execution_approval_digest"], now=NOW + 2)
        coordinator.rpc = FakeRpc(self.x402_journal, execution_id)
        result = coordinator.submit_signature_and_execute(execution_id, signature=SIG, now=NOW + 3)
        self.assertEqual(facilitator.calls, ["verify", "settle"])
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["verification"], {"verdict": "VERIFIED", "errors": []})
        self.assertEqual(self.x402_journal.get(execution_id).state, "CONSUMED")
        self.assertEqual(self.commercial_journal.get(self.prepared["grant"]["grant_id"]).state, "CONSUMED")
        self.assertEqual(result["action_receipt"]["eip3009_nonce"], out["authorization"]["nonce"])

    def test_settlement_pending_is_reconcile_only_and_does_not_reexecute(self):
        facilitator = FakeFacilitator(settle_mode="pending")
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        execution_id = out["execution_id"]
        coordinator.confirm(execution_id, execution_approval_digest=out["execution_approval_digest"], now=NOW + 2)
        pending = coordinator.submit_signature_and_execute(execution_id, signature=SIG, now=NOW + 3)
        self.assertEqual(pending["status"], "IN_DOUBT")
        self.assertEqual(pending["retry"], "reconcile-only")
        self.assertEqual(self.x402_journal.get(execution_id).state, "IN_DOUBT")
        self.assertEqual(self.commercial_journal.get(self.prepared["grant"]["grant_id"]).state, "IN_DOUBT")
        context = self.x402_journal.context(execution_id)
        artifact_digest = context["reference_action_receipt"]["artifact_digest"]
        coordinator.rpc = FakeRpc(self.x402_journal, execution_id)
        result = coordinator.reconcile(execution_id, now=NOW + 4)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(self.x402_journal.context(execution_id)["reference_action_receipt"]["artifact_digest"], artifact_digest)
        self.assertEqual(facilitator.calls, ["verify", "settle"])

    def test_wrong_amount_never_creates_authorization(self):
        coordinator, _ = self.coordinator()
        with self.assertRaisesRegex(CommercialX402Error, "x402-exact-requirement-not-unique"):
            coordinator.prepare(
                self.prepared["grant"]["grant_id"],
                commercial_approval_digest=self.prepared["approval_digest"],
                capability_payload=self.capability_payload,
                payment_required=payment_required(amount="29999"),
                payer=PAYER,
                now=NOW + 1,
            )
        self.assertIsNone(self.x402_journal.get_by_grant(self.prepared["grant"]["grant_id"]))

    def test_signed_and_resource_evidence_are_write_once_anchors(self):
        facilitator = FakeFacilitator(settle_mode="pending")
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        execution_id = out["execution_id"]
        coordinator.confirm(
            execution_id, execution_approval_digest=out["execution_approval_digest"], now=NOW + 2
        )
        pending = coordinator.submit_signature_and_execute(execution_id, signature=SIG, now=NOW + 3)
        self.assertEqual(pending["status"], "IN_DOUBT")
        record = self.x402_journal.get(execution_id)
        self.assertTrue(record.signed_evidence_digest)
        self.assertTrue(record.resource_result_digest)

        context = self.x402_journal.context(execution_id)
        context["payment_payload"]["payload"]["signature"] = "0x" + "22" * 65
        self.x402_journal.replace_context(execution_id, context)
        coordinator.rpc = FakeRpc(self.x402_journal, execution_id)
        with self.assertRaisesRegex(CommercialX402Error, "x402-signed-evidence-context-mismatch"):
            coordinator.reconcile(execution_id, now=NOW + 4)

    def test_resource_result_tamper_is_detected_before_reconciliation(self):
        facilitator = FakeFacilitator(settle_mode="pending")
        coordinator, _ = self.coordinator(facilitator)
        out = self.prepare_x402(coordinator)
        execution_id = out["execution_id"]
        coordinator.confirm(
            execution_id, execution_approval_digest=out["execution_approval_digest"], now=NOW + 2
        )
        coordinator.submit_signature_and_execute(execution_id, signature=SIG, now=NOW + 3)
        context = self.x402_journal.context(execution_id)
        context["artifact"]["confidence_bps"] = 9999
        self.x402_journal.replace_context(execution_id, context)
        coordinator.rpc = FakeRpc(self.x402_journal, execution_id)
        with self.assertRaisesRegex(CommercialX402Error, "x402-resource-result-context-mismatch"):
            coordinator.reconcile(execution_id, now=NOW + 4)

    def test_payment_required_extensions_are_approved_and_echoed(self):
        extensions = {
            "com.example.policy": {
                "info": {"purpose": "release-validation"},
                "schema": {"type": "object"},
            }
        }
        facilitator = FakeFacilitator(verify_valid=False)
        coordinator, _ = self.coordinator(facilitator)
        prepared = coordinator.prepare(
            self.prepared["grant"]["grant_id"],
            commercial_approval_digest=self.prepared["approval_digest"],
            capability_payload=self.capability_payload,
            payment_required=payment_required(extensions=extensions),
            payer=PAYER, now=NOW + 1,
        )
        coordinator.confirm(
            prepared["execution_id"],
            execution_approval_digest=prepared["execution_approval_digest"],
            now=NOW + 2,
        )
        with self.assertRaisesRegex(CommercialX402Error, "x402-facilitator-verification-failed"):
            coordinator.submit_signature_and_execute(prepared["execution_id"], signature=SIG, now=NOW + 3)
        self.assertEqual(facilitator.last_verify_payload["extensions"], extensions)
        self.assertEqual(
            facilitator.last_verify_payload["resource"]["description"],
            "render verify",
        )


if __name__ == "__main__":
    unittest.main()
