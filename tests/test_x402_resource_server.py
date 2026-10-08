import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.facilitator_admission import (
    FacilitatorBinding,
    FacilitatorCapabilityEvidence,
    FacilitatorProbeEvidence,
    FacilitatorRegistry,
    FacilitatorTransportProof,
)
from src.model import Settlement
from src.provider_admission import ProviderBinding, ProviderRegistry
from src.x402 import EIP3009Authorization, payment_payload
from src.x402_resource_server import (
    X402CodeAnalysisResource,
    X402ResourceError,
    X402ResourceJournal,
    _b64_json,
)


NOW = 1_800_000_000
PAYER = "0x1111111111111111111111111111111111111111"
RECIPIENT = "0xebd095378327f025e7d5852868cb7366627aadfc"
TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
PIN = "sha256:" + "ab" * 32
TX = "0x" + "44" * 32
SIG = "0x" + "11" * 32 + "22" * 32 + "1b"


def provider_registry():
    binding = ProviderBinding(
        provider_id="provider:altru-agentpay",
        legal_identity="Valentyn Rukhaylo / Altru.dev (individual operator)",
        capability="agentpay.code-analysis-v1",
        adapter_id="https://agentpay.altru.dev/api/x402/code-analysis",
        request_schema="agentpay-code-analysis-request/1",
        response_schema="agentpay-code-analysis-result/1",
        observation_schema="agentpay-code-analysis-observation/1",
        payment_recipient=RECIPIENT,
        settlement_asset="USDC",
        allowed_disclosures=("document",),
        maximum_retention_seconds=0,
        evidence_types=(
            "execution_receipt",
            "result_observation",
            "settlement_observation",
        ),
        idempotency_model="single-use-request-id",
        cancellation_model="non-cancellable-after-dispatch",
        observation_model="signed-result-plus-independent-fetch",
        jurisdiction="CA",
        valid_from=NOW - 60,
        valid_until=NOW + 3600,
        version=1,
    )
    registry = ProviderRegistry()
    admission = registry.admit(binding, now=NOW)
    assert admission.decision == "ADMIT"
    return registry


def facilitator_registry():
    evidence = FacilitatorProbeEvidence(
        facilitator_id="facilitator:xpay-public-v2",
        verify_url="https://facilitator.xpay.sh/verify",
        settle_url="https://facilitator.xpay.sh/settle",
        resolved_host="facilitator.xpay.sh",
        resolved_addresses=("203.0.113.10",),
        tls_spki_sha256=PIN,
        tls_cert_sha256="sha256:cert",
        tls_subject="CN=*.xpay.sh",
        tls_issuer="CN=Test CA",
        verify_unauthenticated_status=400,
        settle_unauthenticated_status=400,
        observer="frequency:test",
        observed_at=NOW - 30,
    )
    capability = FacilitatorCapabilityEvidence(
        facilitator_id="facilitator:xpay-public-v2",
        supported_url="https://facilitator.xpay.sh/supported",
        supported_response_digest="sha256:supported",
        schemes=("exact",),
        networks=("eip155:8453",),
        authenticated=False,
        observer="frequency:test",
        observed_at=NOW - 30,
        valid_until=NOW + 600,
        access_model="public",
    )
    binding = FacilitatorBinding(
        facilitator_id="facilitator:xpay-public-v2",
        legal_identity="Agentically Inc. (d/b/a xpay)",
        verify_url="https://facilitator.xpay.sh/verify",
        settle_url="https://facilitator.xpay.sh/settle",
        schemes=("exact",),
        networks=("eip155:8453",),
        asset_contracts=(TOKEN,),
        dns_names=("facilitator.xpay.sh",),
        tls_spki_sha256=(PIN,),
        transport="https-json",
        valid_from=NOW - 60,
        valid_until=NOW + 3600,
        version=1,
    )
    proof = FacilitatorTransportProof(
        facilitator_id=binding.facilitator_id,
        verify_url=binding.verify_url,
        settle_url=binding.settle_url,
        resolved_host=evidence.resolved_host,
        tls_spki_sha256=PIN,
        verify_behavior="not-used-local-independent",
        settle_behavior="settlement-only",
        independent_probe=True,
        probe_evidence_digest=evidence.digest,
        observer=evidence.observer,
        observed_at=evidence.observed_at,
        valid_until=NOW + 600,
    )
    registry = FacilitatorRegistry()
    admission = registry.admit(binding, proof, evidence, capability, now=NOW)
    assert admission.decision == "ADMIT"
    return registry


class FakeFacilitator:
    facilitator_id = "facilitator:xpay-public-v2"
    verify_url = "https://facilitator.xpay.sh/verify"
    settle_url = "https://facilitator.xpay.sh/settle"
    tls_spki_sha256 = PIN

    def __init__(self, journal, mode="success"):
        self.journal = journal
        self.mode = mode
        self.calls = 0
        self.states_at_settle = []

    def settle(self, payload, requirement):
        self.calls += 1
        with sqlite3.connect(self.journal.path) as conn:
            row = conn.execute(
                "SELECT state,artifact_json,resource_result_digest FROM x402_resource_execution"
            ).fetchone()
        self.states_at_settle.append(row)
        if self.mode == "lost-response":
            raise RuntimeError("connection-lost-after-broadcast")
        return {
            "success": True,
            "transaction": TX,
            "network": "eip155:8453",
            "payer": PAYER,
        }


class X402ResourceServerTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(path)
        self.path = path
        self.journal = X402ResourceJournal(path)
        self.facilitator = FakeFacilitator(self.journal)
        self.resource = X402CodeAnalysisResource(
            provider_registry=provider_registry(),
            provider_id="provider:altru-agentpay",
            facilitator_registry=facilitator_registry(),
            facilitator=self.facilitator,
            facilitator_id="facilitator:xpay-public-v2",
            rpc=object(),
            journal=self.journal,
            authorization_verifier=lambda rpc, req, auth, sig, now: {
                "isValid": True,
                "payer": auth.from_address,
                "verificationSource": "local-independent",
                "verificationDigest": "local:test",
            },
        )

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def paid_header(self, document):
        challenge = self.resource.challenge(document, now=NOW)
        requirement = challenge["requirement"]
        authorization = EIP3009Authorization(
            from_address=PAYER,
            to=requirement.pay_to,
            value=requirement.amount,
            valid_after=NOW - 1,
            valid_before=NOW + 60,
            nonce="0x" + "33" * 32,
        )
        payload = payment_payload(
            requirement,
            authorization,
            SIG,
            resource=challenge["payment_required"]["resource"],
            extensions={},
        )
        return _b64_json(payload)

    def test_challenge_is_standard_v2_and_bound_to_request_digest(self):
        challenge = self.resource.challenge("print('hello')", now=NOW)
        required = challenge["payment_required"]
        self.assertEqual(required["x402Version"], 2)
        self.assertEqual(required["accepts"][0]["network"], "eip155:8453")
        self.assertEqual(required["accepts"][0]["amount"], "250000")
        self.assertIn("?request=", required["resource"]["url"])
        self.assertTrue(challenge["payment_required_header"])

    def test_resource_is_durable_before_settlement_and_duplicate_does_not_resettle(self):
        document = "password = 'secret'"
        header = self.paid_header(document)
        with patch(
            "src.x402_resource_server.observe_eip3009_settlement",
            return_value=Settlement(
                chain_id=8453,
                transaction_hash=TX,
                sender=PAYER,
                recipient=RECIPIENT,
                asset_contract=TOKEN,
                amount_atomic=250000,
                status="FINALIZED",
            ),
        ):
            first = self.resource.execute(
                document, payment_signature_header=header, now=NOW
            )
            second = self.resource.execute(
                document, payment_signature_header=header, now=NOW + 1
            )
        self.assertEqual(first["status"], "VERIFIED")
        self.assertEqual(first["receipt"]["state"], "CONSUMED")
        self.assertEqual(second["receipt"]["digest"], first["receipt"]["digest"])
        self.assertEqual(self.facilitator.calls, 1)
        state, artifact_json, result_digest = self.facilitator.states_at_settle[0]
        self.assertEqual(state, "SETTLEMENT_PENDING")
        self.assertIsNotNone(artifact_json)
        self.assertIsNotNone(result_digest)

    def test_lost_settle_response_reconciles_by_nonce_without_resettle(self):
        document = "token = 'bounded'"
        header = self.paid_header(document)
        self.facilitator.mode = "lost-response"
        with self.assertRaisesRegex(X402ResourceError, "x402-resource-settlement-unavailable"):
            self.resource.execute(document, payment_signature_header=header, now=NOW)
        with sqlite3.connect(self.journal.path) as conn:
            state = conn.execute("SELECT state FROM x402_resource_execution").fetchone()[0]
        self.assertEqual(state, "SETTLEMENT_PENDING")
        with (
            patch("src.x402_resource_server.find_eip3009_settlement_transaction", return_value=TX),
            patch(
                "src.x402_resource_server.observe_eip3009_settlement",
                return_value=Settlement(
                    chain_id=8453,
                    transaction_hash=TX,
                    sender=PAYER,
                    recipient=RECIPIENT,
                    asset_contract=TOKEN,
                    amount_atomic=250000,
                    status="FINALIZED",
                ),
            ),
        ):
            recovered = self.resource.execute(
                document, payment_signature_header=header, now=NOW + 1
            )
        self.assertEqual(recovered["status"], "VERIFIED")
        self.assertEqual(recovered["receipt"]["state"], "CONSUMED")
        self.assertEqual(self.facilitator.calls, 1)

    def test_requirement_substitution_fails_before_settlement(self):
        document = "safe = True"
        challenge = self.resource.challenge(document, now=NOW)
        requirement = challenge["requirement"]
        authorization = EIP3009Authorization(
            from_address=PAYER,
            to=requirement.pay_to,
            value=requirement.amount,
            valid_after=NOW - 1,
            valid_before=NOW + 60,
            nonce="0x" + "44" * 32,
        )
        payload = payment_payload(
            requirement,
            authorization,
            SIG,
            resource=challenge["payment_required"]["resource"],
            extensions={},
        )
        payload["accepted"]["amount"] = "1"
        with self.assertRaisesRegex(
            X402ResourceError, "x402-payment-payload-requirement-mismatch"
        ):
            self.resource.execute(
                document, payment_signature_header=_b64_json(payload), now=NOW
            )
        self.assertEqual(self.facilitator.calls, 0)


if __name__ == "__main__":
    unittest.main()
