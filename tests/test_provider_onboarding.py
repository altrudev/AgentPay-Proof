import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.provider_endpoint_probe import ProviderEndpointObservation
from src.provider_onboarding import (
    build_signed_provider_manifest,
    create_provider_recipient_challenge,
    provider_binding,
)
from src.provider_recipient_proof import verify_recipient_signature
from src.provider_profile import (
    AGENTPAY_PROVIDER_ADAPTER_URL,
    AGENTPAY_PROVIDER_DOMAIN,
    AGENTPAY_PROVIDER_ID,
    AGENTPAY_PROVIDER_KEY_ID,
    AGENTPAY_PROVIDER_RECIPIENT,
)


NOW = 1_800_000_000


class ProviderOnboardingTests(unittest.TestCase):
    def test_challenge_binds_canonical_provider_profile(self):
        challenge = create_provider_recipient_challenge(
            now=NOW, nonce="ab" * 32
        )
        self.assertEqual(challenge.provider_id, AGENTPAY_PROVIDER_ID)
        self.assertEqual(challenge.recipient, AGENTPAY_PROVIDER_RECIPIENT)
        self.assertEqual(challenge.domain, AGENTPAY_PROVIDER_DOMAIN)
        self.assertEqual(challenge.endpoint, AGENTPAY_PROVIDER_ADAPTER_URL)
        self.assertIn("not a payment authorization", challenge.message)

    def test_binding_is_short_lived_and_fail_closed(self):
        binding = provider_binding(now=NOW, version=1)
        self.assertEqual(binding.version, 1)
        self.assertEqual(binding.maximum_retention_seconds, 0)
        self.assertLessEqual(binding.valid_until - NOW, 86_400)

    def test_build_manifest_signs_exact_evidence_and_self_verifies(self):
        key = Ed25519PrivateKey.generate()
        public_raw = key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        public_b64 = base64.b64encode(public_raw).decode("ascii")
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "provider.pem"
            path.write_bytes(pem)
            path.chmod(0o600)
            challenge = create_provider_recipient_challenge(
                now=NOW, nonce="cd" * 32
            )
            observation = ProviderEndpointObservation(
                provider_id=AGENTPAY_PROVIDER_ID,
                base_url="https://agentpay.altru.dev",
                resolved_host="agentpay.altru.dev",
                resolved_addresses=("203.0.113.10",),
                tls_spki_sha256="sha256:spki",
                tls_cert_sha256="sha256:cert",
                tls_subject="CN=agentpay.altru.dev",
                tls_issuer="CN=Test CA",
                health_document={
                    "ok": True,
                    "live_enabled": True,
                    "live_chain_id": 8453,
                },
                identity_document={
                    "provider_id": AGENTPAY_PROVIDER_ID,
                    "domain": AGENTPAY_PROVIDER_DOMAIN,
                    "issuer_key_id": AGENTPAY_PROVIDER_KEY_ID,
                    "adapter_url": AGENTPAY_PROVIDER_ADAPTER_URL,
                    "payment_recipient": AGENTPAY_PROVIDER_RECIPIENT,
                },
                discovery_document={"service_id": "code-analysis-v1"},
                observed_at=NOW,
                observer="frequency:test-provider-observer",
            )
            with (
                patch(
                    "src.provider_onboarding.AGENTPAY_PROVIDER_PUBLIC_KEY_B64",
                    public_b64,
                ),
                patch(
                    "src.provider_onboarding.probe_provider_endpoint",
                    return_value=observation,
                ),
                patch(
                    "src.provider_evidence_verifiers.verify_recipient_signature",
                    side_effect=lambda challenge, signature, now: verify_recipient_signature(
                        challenge,
                        signature=signature,
                        now=now,
                        recover_address=lambda message, signature: AGENTPAY_PROVIDER_RECIPIENT,
                    ),
                ),
            ):
                manifest = build_signed_provider_manifest(
                    recipient_signature="0x" + "11" * 65,
                    challenge=challenge,
                    now=NOW + 1,
                    version=1,
                    signing_key_path=path,
                    observer="frequency:test-provider-observer",
                    recover_address=lambda message, signature: AGENTPAY_PROVIDER_RECIPIENT,
                )
        self.assertEqual(manifest.provider_id, AGENTPAY_PROVIDER_ID)
        self.assertNotEqual(manifest.signature, "UNSIGNED")
        self.assertEqual(len(manifest.evidence), 3)


if __name__ == "__main__":
    unittest.main()
