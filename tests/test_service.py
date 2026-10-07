import copy
import unittest

from src.protocol import catalog_document, discovery_document, load_quote, quote_document
from src.service import (
    DEFAULT_PRICE_ATOMIC,
    SERVICE_ID,
    SERVICE_SPECS,
    ServiceRequest,
    create_quote,
    execute,
    resolve_service_id,
)


class PaidServiceTests(unittest.TestCase):
    NOW = 1_800_000_000

    def test_discovery_is_machine_readable_and_priced(self):
        doc = discovery_document()
        self.assertEqual(doc["schema"], "agentpay-service/1")
        self.assertEqual(doc["service_id"], SERVICE_ID)
        self.assertEqual(doc["quote"]["price_asset"], "USDC")
        self.assertEqual(doc["quote"]["price_atomic"], DEFAULT_PRICE_ATOMIC)

    def test_catalog_contains_three_real_services(self):
        doc = catalog_document()
        self.assertEqual(doc["schema"], "agentpay-catalog/1")
        self.assertEqual([s["slug"] for s in doc["services"]], ["code", "research", "3d"])
        self.assertEqual(len({s["service_id"] for s in doc["services"]}), 3)

    def test_slug_resolves_to_service_id(self):
        self.assertEqual(resolve_service_id("research"), "data-research-v1")
        with self.assertRaisesRegex(ValueError, "service-unknown"):
            resolve_service_id("unknown")

    def test_quote_binds_exact_service_and_request(self):
        req = ServiceRequest("First sentence. Second sentence. Third sentence.", "research")
        doc = quote_document(req, now=self.NOW)
        quote = load_quote(doc)
        self.assertEqual(quote.request_digest, req.digest)
        self.assertEqual(quote.service_id, "data-research-v1")
        self.assertEqual(quote.amount_atomic, SERVICE_SPECS["data-research-v1"]["price_atomic"])

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

    def test_code_analysis_returns_deterministic_findings(self):
        req = ServiceRequest("password = 'demo'\nTODO: remove eval(x)\neval(x)", "code")
        quote = create_quote(req, now=self.NOW)
        artifact, result = execute(req, quote, now=self.NOW + 1)
        self.assertEqual(artifact["service_id"], "code-analysis-v1")
        self.assertGreaterEqual(artifact["finding_count"], 3)
        self.assertEqual(result.service_id, "code-analysis-v1")
        self.assertEqual(result.request_digest, req.digest)

    def test_research_returns_summary_and_keywords(self):
        req = ServiceRequest("Frequency verifies bounded actions. AgentPay binds payment evidence. Extra context.", "research")
        quote = create_quote(req, now=self.NOW)
        artifact, _ = execute(req, quote, now=self.NOW + 1)
        self.assertEqual(artifact["service_id"], "data-research-v1")
        self.assertIn("Frequency verifies bounded actions.", artifact["summary"])
        self.assertTrue(artifact["keywords"])

    def test_3d_returns_portable_obj(self):
        req = ServiceRequest("AgentPay proof cube", "3d")
        quote = create_quote(req, now=self.NOW)
        artifact, _ = execute(req, quote, now=self.NOW + 1)
        self.assertEqual(artifact["format"], "obj")
        self.assertEqual(artifact["vertex_count"], 8)
        self.assertEqual(artifact["face_count"], 6)
        self.assertIn("o AgentPayCube", artifact["obj"])


if __name__ == "__main__":
    unittest.main()
