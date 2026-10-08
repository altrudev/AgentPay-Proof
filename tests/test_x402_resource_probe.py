import base64
import json
import unittest

from src.x402_resource_probe import (
    X402ResourceProbeError,
    decode_payment_required_header,
)


class X402ResourceProbeTests(unittest.TestCase):
    def test_decodes_v2_payment_required(self):
        value = {
            "x402Version": 2,
            "resource": {"url": "/paid"},
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
        encoded = base64.b64encode(json.dumps({"x402Version": 1, "accepts": [{}]}).encode()).decode()
        with self.assertRaisesRegex(X402ResourceProbeError, "x402-payment-required-v2-invalid"):
            decode_payment_required_header(encoded)


if __name__ == "__main__":
    unittest.main()
