import unittest

from src.facilitator_admission import (
    FacilitatorBinding,
    FacilitatorProbeEvidence,
    FacilitatorRegistry,
    FacilitatorTransportProof,
)

NOW = 1_800_000_000
TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
PIN = "sha256:test-spki"


def binding():
    return FacilitatorBinding(
        facilitator_id="facilitator:test",
        legal_identity="External Test Facilitator Ltd.",
        verify_url="https://facilitator.example/verify",
        settle_url="https://facilitator.example/settle",
        schemes=("exact",),
        networks=("eip155:8453",),
        asset_contracts=(TOKEN,),
        dns_names=("facilitator.example",),
        tls_spki_sha256=(PIN,),
        transport="https-json",
        valid_from=NOW - 60,
        valid_until=NOW + 3600,
        version=1,
    )


def evidence(**overrides):
    values = {
        "facilitator_id": "facilitator:test",
        "verify_url": "https://facilitator.example/verify",
        "settle_url": "https://facilitator.example/settle",
        "resolved_host": "facilitator.example",
        "resolved_addresses": ("203.0.113.10",),
        "tls_spki_sha256": PIN,
        "tls_cert_sha256": "sha256:test-cert",
        "tls_subject": "CN=facilitator.example",
        "tls_issuer": "CN=Test CA",
        "verify_unauthenticated_status": 401,
        "settle_unauthenticated_status": 401,
        "observer": "frequency:test-observer",
        "observed_at": NOW - 30,
    }
    values.update(overrides)
    return FacilitatorProbeEvidence(**values)


def proof(**overrides):
    values = {
        "facilitator_id": "facilitator:test",
        "verify_url": "https://facilitator.example/verify",
        "settle_url": "https://facilitator.example/settle",
        "resolved_host": "facilitator.example",
        "tls_spki_sha256": PIN,
        "verify_behavior": "verification-only",
        "settle_behavior": "settlement-only",
        "independent_probe": True,
        "probe_evidence_digest": evidence().digest,
        "observer": "frequency:test-observer",
        "observed_at": NOW - 30,
        "valid_until": NOW + 600,
    }
    values.update(overrides)
    return FacilitatorTransportProof(**values)


class FacilitatorAdmissionTests(unittest.TestCase):
    def test_admits_exact_bound_transport(self):
        registry = FacilitatorRegistry()
        admission = registry.admit(binding(), proof(), evidence(), now=NOW)
        self.assertEqual(admission.decision, "ADMIT")
        required = registry.require(
            "facilitator:test",
            scheme="exact",
            network="eip155:8453",
            asset_contract=TOKEN,
            now=NOW + 1,
        )
        self.assertEqual(required[0].facilitator_id, "facilitator:test")

    def test_probe_evidence_substitution_is_denied(self):
        registry = FacilitatorRegistry()
        changed = evidence(resolved_addresses=("203.0.113.11",))
        admission = registry.admit(binding(), proof(), changed, now=NOW)
        self.assertEqual(admission.decision, "DENY")
        self.assertIn("facilitator-probe-evidence-mismatch", admission.reasons)

    def test_dns_substitution_is_denied(self):
        registry = FacilitatorRegistry()
        admission = registry.admit(binding(), proof(resolved_host="evil.example"), evidence(), now=NOW)
        self.assertEqual(admission.decision, "DENY")
        self.assertIn("facilitator-proof-dns-mismatch", admission.reasons)

    def test_tls_substitution_is_denied(self):
        registry = FacilitatorRegistry()
        admission = registry.admit(binding(), proof(tls_spki_sha256="sha256:other"), evidence(), now=NOW)
        self.assertEqual(admission.decision, "DENY")
        self.assertIn("facilitator-proof-tls-pin-mismatch", admission.reasons)

    def test_verify_settle_role_confusion_is_denied(self):
        registry = FacilitatorRegistry()
        admission = registry.admit(
            binding(),
            proof(verify_behavior="verification-and-settlement"),
            evidence(),
            now=NOW,
        )
        self.assertEqual(admission.decision, "DENY")
        self.assertIn("facilitator-verify-behavior-unproven", admission.reasons)

    def test_payment_scope_mismatch_fails_closed(self):
        registry = FacilitatorRegistry()
        self.assertEqual(registry.admit(binding(), proof(), evidence(), now=NOW).decision, "ADMIT")
        with self.assertRaisesRegex(ValueError, "facilitator-network-not-admitted"):
            registry.require(
                "facilitator:test",
                scheme="exact",
                network="eip155:1",
                asset_contract=TOKEN,
                now=NOW + 1,
            )


if __name__ == "__main__":
    unittest.main()
