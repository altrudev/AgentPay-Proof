import io
import unittest
from unittest.mock import patch

from src.facilitator_client import (
    FacilitatorClientError,
    FacilitatorRuntimeConfig,
    HTTPX402Facilitator,
    supports_exact_scope,
)


PIN = "sha256:" + "ab" * 32


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FacilitatorClientTests(unittest.TestCase):
    def client(self, token_provider=lambda **_: "jwt"):
        return HTTPX402Facilitator(
            FacilitatorRuntimeConfig(
                facilitator_id="facilitator:test",
                base_url="https://facilitator.example/v2/x402",
                tls_spki_sha256=PIN,
            ),
            token_provider=token_provider,
        )

    def test_supported_binds_token_to_exact_method_host_path(self):
        calls = []

        def token_provider(**kwargs):
            calls.append(kwargs)
            return "short-lived-jwt"

        client = self.client(token_provider)
        with (
            patch(
                "src.facilitator_client._tls_observation",
                return_value={"tls_spki_sha256": PIN},
            ),
            patch("src.facilitator_client.build_opener") as build,
        ):
            build.return_value.open.return_value = FakeResponse(
                b'{"kinds":{"2":[{"scheme":"exact","network":"eip155:8453"}]}}'
            )
            result = client.supported()
        self.assertTrue(supports_exact_scope(result, x402_version=2, network="eip155:8453"))
        self.assertEqual(
            calls,
            [{"method": "GET", "host": "facilitator.example", "path": "/v2/x402/supported"}],
        )


    def test_redirect_is_not_followed(self):
        client = self.client()
        with (
            patch(
                "src.facilitator_client._tls_observation",
                return_value={"tls_spki_sha256": PIN},
            ),
            patch("src.facilitator_client.build_opener") as build,
        ):
            build.return_value.open.side_effect = FacilitatorClientError("facilitator-runtime-redirect")
            with self.assertRaisesRegex(FacilitatorClientError, "facilitator-runtime-redirect"):
                client.supported()

    def test_runtime_tls_substitution_fails_before_token_release(self):
        calls = []

        def token_provider(**kwargs):
            calls.append(kwargs)
            return "jwt"

        client = self.client(token_provider)
        with patch(
            "src.facilitator_client._tls_observation",
            return_value={"tls_spki_sha256": "sha256:" + "cd" * 32},
        ):
            with self.assertRaisesRegex(FacilitatorClientError, "facilitator-runtime-spki-mismatch"):
                client.supported()
        self.assertEqual(calls, [])

    def test_public_facilitator_sends_no_authorization_header(self):
        client = HTTPX402Facilitator(
            FacilitatorRuntimeConfig(
                facilitator_id="facilitator:public",
                base_url="https://facilitator.example",
                tls_spki_sha256=PIN,
            )
        )
        with (
            patch(
                "src.facilitator_client._tls_observation",
                return_value={"tls_spki_sha256": PIN},
            ),
            patch("src.facilitator_client.build_opener") as build,
        ):
            build.return_value.open.return_value = FakeResponse(b'{"kinds":[]}')
            client.supported()
            request = build.return_value.open.call_args.args[0]
            self.assertIsNone(request.get_header("Authorization"))

    def test_missing_token_fails_closed(self):
        client = self.client(lambda **_: "")
        with patch(
            "src.facilitator_client._tls_observation",
            return_value={"tls_spki_sha256": PIN},
        ):
            with self.assertRaisesRegex(FacilitatorClientError, "facilitator-runtime-token-unavailable"):
                client.supported()

    def test_supported_rejects_wrong_network(self):
        response = {"kinds": {"2": [{"scheme": "exact", "network": "eip155:84532"}]}}
        self.assertFalse(supports_exact_scope(response, x402_version=2, network="eip155:8453"))

    def test_legacy_supported_shape_is_accepted(self):
        response = {
            "kinds": [
                {"x402Version": 2, "scheme": "exact", "network": "eip155:8453"},
            ]
        }
        self.assertTrue(supports_exact_scope(response, x402_version=2, network="eip155:8453"))


if __name__ == "__main__":
    unittest.main()
