import copy
import unittest

from src.protocol import discovery_document, load_quote, quote_document
from src.service import (
    DEFAULT_PRICE_ATOMIC, SERVICE_ID, ServiceRequest, create_quote, execute
)


class PaidServiceTests(unittest.TestCase):
    NOW = 1_800_000_000

    def test_discovery_is_machine_readable_and_priced(self):
        doc = discovery_document()
        self.assertEqual(doc["schema"], "agentpay-service/1")
        self.assertEqual(doc["service_id"], SERVICE_ID)
        self.assertEqual(doc["quote"]["price_asset"], "USDC")
        self.assertEqual(doc["quote"]["price_atomic"], DEFAULT_PRICE_ATOMIC)

    def test_quote_binds_exact_request(self):
        req = ServiceRequest("First sentence. Second sentence. Third sentence.")
        doc = quote_document(req, now=self.NOW)
        quote = load_quote(doc)
        self.assertEqual(quote.request_digest, req.digest)
        self.assertEqual(quote.amount_atomic, 250_000)

    def test_tampered_quote_rejected(self):
        req = ServiceRequest("A document.")
        doc = quote_document(req, now=self.NOW)
        doc["quote"]["amount_atomic"] = 1
        with self.assertRaisesRegex(ValueError, "quote-digest-invalid"):
            load_quote(doc)

    def test_service_refuses_request_substitution(self):
        original = ServiceRequest("Original document.")
        changed = ServiceRequest("Different document.")
        quote = create_quote(original, now=self.NOW)
        with self.assertRaisesRegex(PermissionError, "request-binding-mismatch"):
            execute(changed, quote, now=self.NOW + 1)

    def test_expired_quote_refused(self):
        req = ServiceRequest("A document.")
        quote = create_quote(req, now=self.NOW)
        with self.assertRaisesRegex(PermissionError, "quote-expired"):
            execute(req, quote, now=quote.expires_at + 1)

    def test_execution_result_is_bound_to_request(self):
        req = ServiceRequest("First sentence. Second sentence. Third sentence.")
        quote = create_quote(req, now=self.NOW)
        artifact, result = execute(req, quote, now=self.NOW + 1)
        self.assertEqual(artifact["summary"], "First sentence. Second sentence.")
        self.assertEqual(result.request_digest, req.digest)
        self.assertEqual(result.service_id, SERVICE_ID)


if __name__ == "__main__":
    unittest.main()
