import unittest
from unittest.mock import patch

from src.facilitator_admission import FacilitatorProbeEvidence
from src.xpay_runtime import (
    XPAY_FACILITATOR_ID,
    XPAY_REVIEWED_TLS_SPKI_SHA256,
    XPayRuntimeError,
    build_xpay_runtime,
)


NOW = 1_800_000_000


class FakeClient:
    verify_url = "https://facilitator.xpay.sh/verify"
    settle_url = "https://facilitator.xpay.sh/settle"
    supported_url = "https://facilitator.xpay.sh/supported"
    facilitator_id = XPAY_FACILITATOR_ID
    tls_spki_sha256 = XPAY_REVIEWED_TLS_SPKI_SHA256

    def __init__(self, *args, **kwargs):
        pass

    def supported(self):
        return {
            "kinds": [
                {"x402Version": 2, "scheme": "exact", "network": "eip155:8453"}
            ]
        }


def evidence(spki=XPAY_REVIEWED_TLS_SPKI_SHA256, verify_status=400, settle_status=400):
    return FacilitatorProbeEvidence(
        facilitator_id=XPAY_FACILITATOR_ID,
        verify_url="https://facilitator.xpay.sh/verify",
        settle_url="https://facilitator.xpay.sh/settle",
        resolved_host="facilitator.xpay.sh",
        resolved_addresses=("203.0.113.10",),
        tls_spki_sha256=spki,
        tls_cert_sha256="sha256:cert",
        tls_subject="CN=*.xpay.sh",
        tls_issuer="CN=Test CA",
        verify_unauthenticated_status=verify_status,
        settle_unauthenticated_status=settle_status,
        observer="frequency:test",
        observed_at=NOW,
    )


class XPayRuntimeTests(unittest.TestCase):
    def test_public_base_mainnet_runtime_is_admitted_for_local_verify_only(self):
        with (
            patch("src.xpay_runtime.probe_facilitator_transport", return_value=evidence()),
            patch("src.xpay_runtime.HTTPX402Facilitator", FakeClient),
        ):
            registry, client, fid = build_xpay_runtime(now=NOW)
        binding, proof, admission = registry.require(
            fid,
            scheme="exact",
            network="eip155:8453",
            asset_contract="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            now=NOW + 1,
        )
        self.assertEqual(admission.decision, "ADMIT")
        self.assertEqual(proof.verify_behavior, "not-used-local-independent")
        self.assertEqual(binding.legal_identity, "Agentically Inc. (d/b/a xpay)")

    def test_unexpected_tls_key_fails_closed(self):
        with (
            patch(
                "src.xpay_runtime.probe_facilitator_transport",
                return_value=evidence(spki="sha256:" + "00" * 32),
            ),
            patch("src.xpay_runtime.HTTPX402Facilitator", FakeClient),
        ):
            with self.assertRaisesRegex(XPayRuntimeError, "xpay-reviewed-spki-mismatch"):
                build_xpay_runtime(now=NOW)


if __name__ == "__main__":
    unittest.main()
