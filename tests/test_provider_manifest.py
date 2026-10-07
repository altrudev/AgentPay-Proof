import base64
import importlib.util
import os
import tempfile
import unittest

from src.provider_admission import ProviderBinding
from src.provider_manifest import ProviderEvidence, ProviderManifest, ed25519_verify, verify_provider_manifest
from src.provider_registry_store import ProviderRegistryStore, ProviderStoreError

NOW = 1_800_000_000
RECIPIENT = "0x000000000000000000000000000000000000beef"
HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None


def binding(version=1):
    return ProviderBinding(
        provider_id="provider:external-test",
        legal_identity="External Test Provider Ltd.",
        capability="browser.render.verify",
        adapter_id="https://provider.example/v1/render-verify",
        request_schema="agentpay-render-verify-request/1",
        response_schema="agentpay-render-verify-result/1",
        observation_schema="agentpay-render-verify-observation/1",
        payment_recipient=RECIPIENT,
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
        version=version,
    )


def evidence():
    return (
        ProviderEvidence("identity-control", "provider:external-test", "observer:identity", "registry:entity:123", NOW - 10, NOW + 600, "sha256:identity"),
        ProviderEvidence("recipient-control", "provider:external-test", "observer:wallet", RECIPIENT, NOW - 10, NOW + 600, "sha256:wallet"),
        ProviderEvidence("endpoint-control", "provider:external-test", "observer:endpoint", "https://provider.example/v1/render-verify#adapter=https://provider.example/v1/render-verify", NOW - 10, NOW + 600, "sha256:endpoint"),
    )


def evidence_verifiers():
    return {
        "identity-control": lambda item, manifest: item.issuer == "observer:identity" and item.digest == "sha256:identity",
        "recipient-control": lambda item, manifest: item.issuer == "observer:wallet" and item.digest == "sha256:wallet",
        "endpoint-control": lambda item, manifest: item.issuer == "observer:endpoint" and item.digest == "sha256:endpoint",
    }


@unittest.skipUnless(HAS_CRYPTO, "cryptography optional dependency not installed")
class ProviderManifestTests(unittest.TestCase):
    def keypair(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return private, base64.b64encode(public).decode()

    def signed_manifest(self, version=1):
        private, public_b64 = self.keypair()
        unsigned = ProviderManifest(
            manifest_id=f"manifest:{version}",
            provider_id="provider:external-test",
            binding=binding(version),
            issuer_key_id="provider-key-1",
            signature="pending",
            evidence=evidence(),
            issued_at=NOW - 5,
            expires_at=NOW + 600,
        )
        signature = base64.b64encode(private.sign(unsigned.digest.encode("ascii"))).decode()
        manifest = ProviderManifest(
            manifest_id=unsigned.manifest_id,
            provider_id=unsigned.provider_id,
            binding=unsigned.binding,
            issuer_key_id=unsigned.issuer_key_id,
            signature=signature,
            evidence=unsigned.evidence,
            issued_at=unsigned.issued_at,
            expires_at=unsigned.expires_at,
        )
        return manifest, public_b64

    def test_valid_manifest_verifies(self):
        manifest, public_b64 = self.signed_manifest()
        result = verify_provider_manifest(
            manifest,
            now=NOW,
            signature_verifier=ed25519_verify,
            trusted_issuers={"provider-key-1": public_b64},
            evidence_verifiers=evidence_verifiers(),
        )
        self.assertEqual(result.verdict, "VERIFIED")

    def test_signature_tamper_fails_closed(self):
        manifest, public_b64 = self.signed_manifest()
        tampered = ProviderManifest(
            manifest_id=manifest.manifest_id,
            provider_id=manifest.provider_id,
            binding=binding(2),
            issuer_key_id=manifest.issuer_key_id,
            signature=manifest.signature,
            evidence=manifest.evidence,
            issued_at=manifest.issued_at,
            expires_at=manifest.expires_at,
        )
        result = verify_provider_manifest(tampered, now=NOW, signature_verifier=ed25519_verify, trusted_issuers={"provider-key-1": public_b64}, evidence_verifiers=evidence_verifiers())
        self.assertEqual(result.verdict, "NOT VERIFIED")
        self.assertIn("provider-manifest-signature-invalid", result.reasons)

    def test_missing_verifier_never_downgrades_to_trust(self):
        manifest, public_b64 = self.signed_manifest()
        result = verify_provider_manifest(manifest, now=NOW, signature_verifier=None, trusted_issuers={"provider-key-1": public_b64}, evidence_verifiers=evidence_verifiers())
        self.assertEqual(result.verdict, "NOT VERIFIED")
        self.assertIn("provider-signature-verifier-unavailable", result.reasons)

    def test_recipient_evidence_must_match_binding(self):
        manifest, public_b64 = self.signed_manifest()
        bad_evidence = tuple(
            ProviderEvidence(item.evidence_type, item.subject, item.issuer, "0x000000000000000000000000000000000000dead" if item.evidence_type == "recipient-control" else item.reference, item.observed_at, item.expires_at, item.digest)
            for item in manifest.evidence
        )
        private, public_b64 = self.keypair()
        unsigned = ProviderManifest(manifest.manifest_id, manifest.provider_id, manifest.binding, manifest.issuer_key_id, "pending", bad_evidence, manifest.issued_at, manifest.expires_at)
        signature = base64.b64encode(private.sign(unsigned.digest.encode("ascii"))).decode()
        bad = ProviderManifest(unsigned.manifest_id, unsigned.provider_id, unsigned.binding, unsigned.issuer_key_id, signature, unsigned.evidence, unsigned.issued_at, unsigned.expires_at)
        result = verify_provider_manifest(bad, now=NOW, signature_verifier=ed25519_verify, trusted_issuers={"provider-key-1": public_b64}, evidence_verifiers=evidence_verifiers())
        self.assertIn("provider-recipient-evidence-mismatch", result.reasons)

    def test_persistent_store_admits_versions_and_revocation_survives_reload(self):
        fd, path = tempfile.mkstemp(); os.close(fd); os.unlink(path)
        try:
            store = ProviderRegistryStore(path)
            manifest1, public1 = self.signed_manifest(version=1)
            store.admit_manifest(manifest1, now=NOW, signature_verifier=ed25519_verify, trusted_issuers={"provider-key-1": public1}, evidence_verifiers=evidence_verifiers())
            registry = store.load_registry(now=NOW, signature_verifier=ed25519_verify, trusted_issuers={"provider-key-1": public1}, evidence_verifiers=evidence_verifiers())
            loaded, _ = registry.require("provider:external-test", "browser.render.verify", now=NOW)
            self.assertEqual(loaded.version, 1)

            with self.assertRaisesRegex(ProviderStoreError, "provider-version-not-monotonic"):
                store.admit_manifest(manifest1, now=NOW, signature_verifier=ed25519_verify, trusted_issuers={"provider-key-1": public1}, evidence_verifiers=evidence_verifiers())

            store.revoke("provider:external-test", now=NOW + 1)
            with self.assertRaisesRegex(ValueError, "provider-not-admitted"):
                store.load_registry(now=NOW + 2, signature_verifier=ed25519_verify, trusted_issuers={"provider-key-1": public1}, evidence_verifiers=evidence_verifiers()).require("provider:external-test", "browser.render.verify", now=NOW + 2)
            self.assertEqual(store.status("provider:external-test")["state"], "REVOKED")
        finally:
            if os.path.exists(path): os.unlink(path)

    def test_missing_independent_evidence_verifier_fails_closed(self):
        manifest, public_b64 = self.signed_manifest()
        result = verify_provider_manifest(
            manifest,
            now=NOW,
            signature_verifier=ed25519_verify,
            trusted_issuers={"provider-key-1": public_b64},
            evidence_verifiers={},
        )
        self.assertEqual(result.verdict, "NOT VERIFIED")
        self.assertTrue(any(r.startswith("provider-evidence-verifier-unavailable:") for r in result.reasons))

    def test_persistent_admission_digest_is_stable_across_reload(self):
        fd, path = tempfile.mkstemp(); os.close(fd); os.unlink(path)
        try:
            store = ProviderRegistryStore(path)
            manifest, public_b64 = self.signed_manifest()
            _, admitted = store.admit_manifest(
                manifest, now=NOW, signature_verifier=ed25519_verify,
                trusted_issuers={"provider-key-1": public_b64},
                evidence_verifiers=evidence_verifiers(),
            )
            _, restored = store.load_registry(now=NOW + 1, signature_verifier=ed25519_verify, trusted_issuers={"provider-key-1": public_b64}, evidence_verifiers=evidence_verifiers()).require(
                "provider:external-test", "browser.render.verify", now=NOW + 1
            )
            self.assertEqual(restored.digest, admitted.digest)
        finally:
            if os.path.exists(path): os.unlink(path)

    def test_signing_key_rotation_requires_explicit_protocol(self):
        fd, path = tempfile.mkstemp(); os.close(fd); os.unlink(path)
        try:
            store = ProviderRegistryStore(path)
            first, first_key = self.signed_manifest(version=1)
            store.admit_manifest(
                first, now=NOW, signature_verifier=ed25519_verify,
                trusted_issuers={"provider-key-1": first_key},
                evidence_verifiers=evidence_verifiers(),
            )
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            private = Ed25519PrivateKey.generate()
            public = base64.b64encode(private.public_key().public_bytes(
                encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
            )).decode()
            unsigned = ProviderManifest(
                manifest_id="manifest:2", provider_id="provider:external-test",
                binding=binding(2), issuer_key_id="provider-key-2", signature="pending",
                evidence=evidence(), issued_at=NOW - 5, expires_at=NOW + 600,
            )
            rotated = ProviderManifest(
                manifest_id=unsigned.manifest_id, provider_id=unsigned.provider_id, binding=unsigned.binding,
                issuer_key_id=unsigned.issuer_key_id,
                signature=base64.b64encode(private.sign(unsigned.digest.encode("ascii"))).decode(),
                evidence=unsigned.evidence, issued_at=unsigned.issued_at, expires_at=unsigned.expires_at,
            )
            with self.assertRaisesRegex(ProviderStoreError, "provider-key-rotation-not-authorized"):
                store.admit_manifest(
                    rotated, now=NOW, signature_verifier=ed25519_verify,
                    trusted_issuers={"provider-key-2": public},
                    evidence_verifiers=evidence_verifiers(),
                )
        finally:
            if os.path.exists(path): os.unlink(path)

    def test_persisted_manifest_tamper_is_detected_on_reload(self):
        import sqlite3
        fd, path = tempfile.mkstemp(); os.close(fd); os.unlink(path)
        try:
            store = ProviderRegistryStore(path)
            manifest, public_b64 = self.signed_manifest()
            store.admit_manifest(
                manifest, now=NOW, signature_verifier=ed25519_verify,
                trusted_issuers={"provider-key-1": public_b64},
                evidence_verifiers=evidence_verifiers(),
            )
            conn = sqlite3.connect(path)
            conn.execute(
                "UPDATE provider_registry SET manifest_digest=? WHERE provider_id=?",
                ("0" * 64, "provider:external-test"),
            )
            conn.commit(); conn.close()
            with self.assertRaisesRegex(ProviderStoreError, "persisted-provider-manifest-digest-mismatch"):
                store.load_registry(
                    now=NOW + 1, signature_verifier=ed25519_verify,
                    trusted_issuers={"provider-key-1": public_b64},
                    evidence_verifiers=evidence_verifiers(),
                )
        finally:
            if os.path.exists(path): os.unlink(path)


if __name__ == "__main__":
    unittest.main()
