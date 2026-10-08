import base64
import json
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from src.cdp_auth import CdpApiKey, CdpAuthError, generate_cdp_jwt


def b64d(value: str) -> bytes:
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value)


class CdpAuthTests(unittest.TestCase):
    def test_ed25519_token_binds_exact_request(self):
        private = ed25519.Ed25519PrivateKey.generate()
        raw = private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        secret = base64.b64encode(raw + public).decode("ascii")
        token = generate_cdp_jwt(
            CdpApiKey(key_id="organizations/test/apiKeys/key", secret=secret),
            method="GET",
            host="api.cdp.coinbase.com",
            path="/platform/v2/x402/supported",
            now=1_800_000_000,
            expires_in=120,
            nonce="1234567890123456",
        )
        h, p, s = token.split(".")
        header = json.loads(b64d(h))
        claims = json.loads(b64d(p))
        self.assertEqual(header["alg"], "EdDSA")
        self.assertEqual(header["kid"], "organizations/test/apiKeys/key")
        self.assertEqual(header["nonce"], "1234567890123456")
        self.assertEqual(claims["iss"], "cdp")
        self.assertEqual(claims["sub"], "organizations/test/apiKeys/key")
        self.assertEqual(claims["nbf"], 1_800_000_000)
        self.assertEqual(claims["exp"], 1_800_000_120)
        self.assertEqual(
            claims["uris"],
            ["GET api.cdp.coinbase.com/platform/v2/x402/supported"],
        )
        private.public_key().verify(b64d(s), f"{h}.{p}".encode("ascii"))

    def test_es256_token_binds_exact_request(self):
        private = ec.generate_private_key(ec.SECP256R1())
        pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode("utf-8")
        token = generate_cdp_jwt(
            CdpApiKey(key_id="key", secret=pem),
            method="POST",
            host="api.cdp.coinbase.com",
            path="/platform/v2/x402/verify",
            now=1_800_000_000,
            nonce="1234567890123456",
        )
        h, p, s = token.split(".")
        header = json.loads(b64d(h))
        self.assertEqual(header["alg"], "ES256")
        sig = b64d(s)
        self.assertEqual(len(sig), 64)
        der = encode_dss_signature(
            int.from_bytes(sig[:32], "big"),
            int.from_bytes(sig[32:], "big"),
        )
        private.public_key().verify(
            der,
            f"{h}.{p}".encode("ascii"),
            ec.ECDSA(hashes.SHA256()),
        )

    def test_expiry_cannot_exceed_cdp_policy(self):
        private = ed25519.Ed25519PrivateKey.generate()
        raw = private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        secret = base64.b64encode(raw + public).decode("ascii")
        with self.assertRaisesRegex(CdpAuthError, "cdp-jwt-expiry-outside-policy"):
            generate_cdp_jwt(
                CdpApiKey(key_id="key", secret=secret),
                method="GET",
                host="api.cdp.coinbase.com",
                path="/platform/v2/x402/supported",
                expires_in=121,
            )

    def test_partial_or_wrong_secret_fails_closed(self):
        with self.assertRaisesRegex(CdpAuthError, "cdp-api-key-secret-format-unsupported"):
            generate_cdp_jwt(
                CdpApiKey(key_id="key", secret="not-a-key"),
                method="GET",
                host="api.cdp.coinbase.com",
                path="/platform/v2/x402/supported",
            )


if __name__ == "__main__":
    unittest.main()
