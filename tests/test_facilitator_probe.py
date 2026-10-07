import unittest
from unittest.mock import patch

from src.facilitator_probe import (
    FacilitatorProbeError,
    FacilitatorProbeTarget,
    probe_facilitator_transport,
)


class FacilitatorProbeTests(unittest.TestCase):
    def test_probe_binds_dns_tls_and_auth_boundary(self):
        target = FacilitatorProbeTarget(
            facilitator_id="facilitator:test",
            verify_url="https://facilitator.example/verify",
            settle_url="https://facilitator.example/settle",
        )
        with (
            patch("src.facilitator_probe._dns_addresses", return_value=("203.0.113.10",)),
            patch(
                "src.facilitator_probe._tls_observation",
                return_value={
                    "tls_spki_sha256": "sha256:spki",
                    "tls_cert_sha256": "sha256:cert",
                    "tls_subject": "CN=facilitator.example",
                    "tls_issuer": "CN=Test CA",
                },
            ),
            patch(
                "src.facilitator_probe._unauthenticated_post_status",
                side_effect=[401, 403],
            ),
        ):
            evidence = probe_facilitator_transport(
                target,
                observer="frequency:test-observer",
                observed_at=1_800_000_000,
            )
        self.assertEqual(evidence.resolved_addresses, ("203.0.113.10",))
        self.assertEqual(evidence.verify_unauthenticated_status, 401)
        self.assertEqual(evidence.settle_unauthenticated_status, 403)
        self.assertTrue(evidence.digest)

    def test_cross_host_verify_settle_is_rejected(self):
        target = FacilitatorProbeTarget(
            facilitator_id="facilitator:test",
            verify_url="https://verify.example/verify",
            settle_url="https://settle.example/settle",
        )
        with self.assertRaisesRegex(FacilitatorProbeError, "facilitator-probe-host-mismatch"):
            _ = target.host


if __name__ == "__main__":
    unittest.main()
