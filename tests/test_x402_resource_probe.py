import base64
import json
import unittest
from unittest.mock import patch

from src.x402_resource_probe import (
    X402ResourceProbeError,
    decode_payment_required_header,
    probe_x402_resource,
)


def encoded_quote(resource_url: str) -> str:
    value = {
        "x402Version": 2,
        "resource": {"url": resource_url},
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "amount": "100000",
                "asset": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                "payTo": "0x631e220fe781083a5571552ce82036d96b158696",
                "maxTimeoutSeconds": 60,
                "extra": {"name": "USD Coin", "version": "2"},
            }
        ],
    }
    return base64.b64encode(json.dumps(value).encode()).decode()


class FakeResponse:
    status = 402

    def __init__(self, header):
        self.headers = {"payment-required": header}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


class X402ResourceProbeTests(unittest.TestCase):
    def test_decodes_v2_payment_required(self):
        value = {
            "x402Version": 2,
            "resource": {"url": "https://paid.example/resource"},
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:8453",
                    "amount": "100000",
                    "asset": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    "payTo": "0x631e220fe781083a5571552ce82036d96b158696",
                    "maxTimeoutSeconds": 60,
                    "extra": {"name": "USD Coin", "version": "2"},
                }
            ],
        }
        encoded = base64.b64encode(json.dumps(value).encode()).decode()
        self.assertEqual(decode_payment_required_header(encoded), value)

    def test_rejects_non_v2_quote(self):
        encoded = base64.b64encode(
            json.dumps({"x402Version": 1, "accepts": [{}]}).encode()
        ).decode()
        with self.assertRaisesRegex(
            X402ResourceProbeError, "x402-payment-required-v2-invalid"
        ):
            decode_payment_required_header(encoded)

    def test_quote_origin_must_match_probed_origin(self):
        resource_url = "https://resource.example/paid"
        opener = FakeOpener(
            FakeResponse(encoded_quote("https://resource.example.evil.test/paid"))
        )
        with patch("src.x402_resource_probe.build_opener", return_value=opener):
            with self.assertRaisesRegex(
                X402ResourceProbeError, "x402-resource-probe-resource-origin-mismatch"
            ):
                probe_x402_resource(
                    resource_url=resource_url,
                    request_body={"query": "select 1"},
                    observer="frequency:test",
                    observed_at=1_800_000_000,
                )

    def test_probe_rejects_userinfo_url(self):
        with self.assertRaisesRegex(
            X402ResourceProbeError, "x402-resource-probe-url-invalid"
        ):
            probe_x402_resource(
                resource_url="https://user@resource.example/paid",
                request_body={"query": "select 1"},
                observer="frequency:test",
                observed_at=1_800_000_000,
            )


if __name__ == "__main__":
    unittest.main()
