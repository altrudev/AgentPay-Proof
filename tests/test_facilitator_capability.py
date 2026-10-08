import unittest

from src.facilitator_capability import (
    FacilitatorCapabilityError,
    capability_evidence_from_supported,
    require_supported_scope,
)


class FacilitatorCapabilityTests(unittest.TestCase):
    def test_version_grouped_supported_response_becomes_evidence(self):
        response = {
            "kinds": {
                "2": [
                    {"scheme": "exact", "network": "eip155:8453"},
                    {"scheme": "exact", "network": "eip155:84532"},
                ]
            }
        }
        evidence = capability_evidence_from_supported(
            facilitator_id="facilitator:test",
            supported_url="https://facilitator.example/supported",
            response=response,
            observer="frequency:test",
            observed_at=100,
            valid_until=200,
        )
        require_supported_scope(evidence, scheme="exact", network="eip155:8453")
        self.assertTrue(evidence.authenticated)
        self.assertTrue(evidence.supported_response_digest)

    def test_public_no_auth_capability_is_explicit(self):
        response = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": "eip155:8453"}]}
        evidence = capability_evidence_from_supported(
            facilitator_id="facilitator:public",
            supported_url="https://facilitator.example/supported",
            response=response,
            observer="frequency:test",
            observed_at=100,
            valid_until=200,
            authenticated=False,
            access_model="public",
        )
        self.assertFalse(evidence.authenticated)
        self.assertEqual(evidence.access_model, "public")
        require_supported_scope(evidence, scheme="exact", network="eip155:8453")

    def test_wrong_network_fails_closed(self):
        response = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": "eip155:84532"}]}
        evidence = capability_evidence_from_supported(
            facilitator_id="facilitator:test",
            supported_url="https://facilitator.example/supported",
            response=response,
            observer="frequency:test",
            observed_at=100,
            valid_until=200,
        )
        with self.assertRaisesRegex(FacilitatorCapabilityError, "facilitator-supported-network-missing"):
            require_supported_scope(evidence, scheme="exact", network="eip155:8453")


if __name__ == "__main__":
    unittest.main()
