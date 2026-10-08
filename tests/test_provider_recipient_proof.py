import unittest

from src.provider_recipient_proof import (
    ProviderRecipientProofError,
    new_recipient_challenge,
    recipient_provider_evidence,
    verify_recipient_signature,
)


NOW = 1_800_000_000
RECIPIENT = "0xebd095378327f025e7d5852868cb7366627aadfc"


def challenge():
    return new_recipient_challenge(
        provider_id="provider:altru-agentpay",
        recipient=RECIPIENT,
        chain_id=8453,
        domain="agentpay.altru.dev",
        endpoint="https://agentpay.altru.dev/api/live/prepare",
        quote_digest="a" * 64,
        now=NOW,
        ttl_seconds=600,
        nonce="b" * 64,
    )


class ProviderRecipientProofTests(unittest.TestCase):
    def test_exact_recipient_signature_creates_evidence(self):
        c = challenge()
        proof = verify_recipient_signature(
            c,
            signature="0x" + "11" * 65,
            now=NOW + 1,
            recover_address=lambda message, signature: RECIPIENT,
        )
        evidence = recipient_provider_evidence(
            c,
            proof,
            issuer="frequency:prometheus-recipient-observer",
            expires_at=NOW + 3600,
        )
        self.assertEqual(evidence.evidence_type, "recipient-control")
        self.assertEqual(evidence.reference, RECIPIENT)
        self.assertTrue(evidence.digest)
        self.assertIn("not a payment authorization", c.message)

    def test_wrong_signer_fails_closed(self):
        c = challenge()
        with self.assertRaisesRegex(ProviderRecipientProofError, "provider-recipient-signer-mismatch"):
            verify_recipient_signature(
                c,
                signature="0x" + "11" * 65,
                now=NOW + 1,
                recover_address=lambda message, signature: "0x1111111111111111111111111111111111111111",
            )

    def test_expired_challenge_fails_closed(self):
        c = challenge()
        with self.assertRaisesRegex(ProviderRecipientProofError, "provider-recipient-challenge-expired"):
            verify_recipient_signature(
                c,
                signature="0x" + "11" * 65,
                now=c.expires_at + 1,
                recover_address=lambda message, signature: RECIPIENT,
            )

    def test_challenge_endpoint_must_match_domain(self):
        with self.assertRaisesRegex(ValueError, "provider-recipient-endpoint-invalid"):
            new_recipient_challenge(
                provider_id="provider:altru-agentpay",
                recipient=RECIPIENT,
                chain_id=8453,
                domain="agentpay.altru.dev",
                endpoint="https://agentpay.altru.dev.evil.test/api/x402/code-analysis",
                quote_digest="a" * 64,
                now=NOW,
                nonce="b" * 64,
            )

    def test_challenge_is_bound_to_quote_endpoint_and_domain(self):
        c = challenge()
        text = c.message
        self.assertIn("agentpay.altru.dev", text)
        self.assertIn("/api/live/prepare", text)
        self.assertIn("a" * 64, text)
        self.assertIn("Chain ID: 8453", text)


if __name__ == "__main__":
    unittest.main()
