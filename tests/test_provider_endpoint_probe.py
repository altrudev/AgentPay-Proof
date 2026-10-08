import unittest
from unittest.mock import patch

from src.provider_endpoint_probe import (
    ProviderEndpointProbeError,
    endpoint_control_evidence,
    identity_control_evidence,
    probe_provider_endpoint,
)


NOW = 1_800_000_000
BASE = "https://agentpay.example"
PROVIDER = "provider:altru-agentpay"


class ProviderEndpointProbeTests(unittest.TestCase):
    def observe(self):
        documents = [
            {"ok": True, "live_enabled": True, "live_chain_id": 8453},
            {"provider_id": PROVIDER, "domain": "agentpay.example"},
            {"service_id": "code-analysis-v1"},
        ]
        with (
            patch(
                "src.provider_endpoint_probe._transport",
                return_value=(
                    ("203.0.113.10",),
                    {
                        "tls_spki_sha256": "sha256:spki",
                        "tls_cert_sha256": "sha256:cert",
                        "tls_subject": "CN=agentpay.example",
                        "tls_issuer": "CN=Test CA",
                    },
                ),
            ),
            patch("src.provider_endpoint_probe._get_json", side_effect=documents),
        ):
            return probe_provider_endpoint(
                provider_id=PROVIDER,
                base_url=BASE,
                service_id="code-analysis-v1",
                observer="frequency:test-provider-observer",
                observed_at=NOW,
            )

    def test_observation_creates_separate_identity_and_endpoint_evidence(self):
        observation = self.observe()
        identity = identity_control_evidence(observation, expires_at=NOW + 3600)
        endpoint = endpoint_control_evidence(
            observation,
            adapter_id=BASE + "/api/live/prepare",
            expires_at=NOW + 3600,
        )
        self.assertEqual(identity.evidence_type, "identity-control")
        self.assertEqual(endpoint.evidence_type, "endpoint-control")
        self.assertNotEqual(identity.digest, endpoint.digest)
        self.assertTrue(observation.digest)

    def test_adapter_outside_observed_origin_fails_closed(self):
        observation = self.observe()
        with self.assertRaisesRegex(
            ProviderEndpointProbeError,
            "provider-endpoint-adapter-outside-observed-origin",
        ):
            endpoint_control_evidence(
                observation,
                adapter_id="https://evil.example/api/live/prepare",
                expires_at=NOW + 3600,
            )

    def test_lookalike_adapter_origin_fails_closed(self):
        observation = self.observe()
        with self.assertRaisesRegex(ProviderEndpointProbeError, "provider-endpoint-adapter-outside-observed-origin"):
            endpoint_control_evidence(
                observation,
                adapter_id="https://agentpay.example.evil.test/api/live/prepare",
                expires_at=NOW + 3600,
            )

    def test_base_url_with_userinfo_fails_closed(self):
        with self.assertRaisesRegex(ProviderEndpointProbeError, "provider-endpoint-base-url-invalid"):
            probe_provider_endpoint(
                provider_id=PROVIDER,
                base_url="https://user@agentpay.example",
                service_id="code-analysis-v1",
                observer="frequency:test",
                observed_at=NOW,
            )

    def test_identity_mismatch_fails_closed(self):
        documents = [
            {"ok": True, "live_enabled": True},
            {"provider_id": "provider:other", "domain": "agentpay.example"},
            {"service_id": "code-analysis-v1"},
        ]
        with (
            patch(
                "src.provider_endpoint_probe._transport",
                return_value=(
                    ("203.0.113.10",),
                    {
                        "tls_spki_sha256": "sha256:spki",
                        "tls_cert_sha256": "sha256:cert",
                        "tls_subject": "CN=agentpay.example",
                        "tls_issuer": "CN=Test CA",
                    },
                ),
            ),
            patch("src.provider_endpoint_probe._get_json", side_effect=documents),
        ):
            with self.assertRaisesRegex(
                ProviderEndpointProbeError, "provider-endpoint-identity-mismatch"
            ):
                probe_provider_endpoint(
                    provider_id=PROVIDER,
                    base_url=BASE,
                    service_id="code-analysis-v1",
                    observer="frequency:test",
                    observed_at=NOW,
                )


if __name__ == "__main__":
    unittest.main()
