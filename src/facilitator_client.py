from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from src.facilitator_probe import FacilitatorProbeError, _tls_observation


class FacilitatorClientError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FacilitatorClientError("facilitator-runtime-redirect")


class BearerTokenProvider(Protocol):
    def __call__(self, *, method: str, host: str, path: str) -> str: ...


@dataclass(frozen=True)
class FacilitatorRuntimeConfig:
    facilitator_id: str
    base_url: str
    tls_spki_sha256: str
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        if not self.facilitator_id.strip():
            raise ValueError("facilitator-runtime-id-required")
        if not self.base_url.startswith("https://"):
            raise ValueError("facilitator-runtime-https-required")
        if not self.tls_spki_sha256.lower().startswith("sha256:"):
            raise ValueError("facilitator-runtime-spki-required")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise ValueError("facilitator-runtime-timeout-invalid")


class HTTPX402Facilitator:
    """Credential-isolated x402 facilitator adapter.

    The token provider is invoked per request. Tokens are never persisted,
    returned, included in exceptions, or stored on the adapter.
    """

    def __init__(
        self,
        config: FacilitatorRuntimeConfig,
        *,
        token_provider: BearerTokenProvider,
    ):
        self.config = config
        self._token_provider = token_provider
        self.facilitator_id = config.facilitator_id
        self.verify_url = config.base_url.rstrip("/") + "/verify"
        self.settle_url = config.base_url.rstrip("/") + "/settle"
        self.supported_url = config.base_url.rstrip("/") + "/supported"
        self.tls_spki_sha256 = config.tls_spki_sha256.lower()

    @property
    def host(self) -> str:
        from urllib.parse import urlsplit
        host = urlsplit(self.config.base_url).hostname
        if not host:
            raise FacilitatorClientError("facilitator-runtime-host-invalid")
        return host.lower()

    @property
    def base_path(self) -> str:
        from urllib.parse import urlsplit
        path = urlsplit(self.config.base_url).path.rstrip("/")
        return path

    def _bound_path(self, path: str) -> str:
        if not path.startswith("/"):
            raise FacilitatorClientError("facilitator-runtime-path-invalid")
        return self.base_path + path

    def _assert_transport_identity(self) -> None:
        try:
            observed = _tls_observation(self.host, timeout=self.config.timeout_seconds)
        except FacilitatorProbeError as exc:
            raise FacilitatorClientError("facilitator-runtime-tls-observation-failed") from exc
        if observed["tls_spki_sha256"].lower() != self.tls_spki_sha256:
            raise FacilitatorClientError("facilitator-runtime-spki-mismatch")

    def _request(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_transport_identity()
        bound_path = self._bound_path(path)
        token = self._token_provider(method=method, host=self.host, path=bound_path)
        if not isinstance(token, str) or not token.strip():
            raise FacilitatorClientError("facilitator-runtime-token-unavailable")
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + token.strip(),
            "User-Agent": "AgentPay-Proof/1 Frequency-Governed",
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.config.base_url.rstrip("/") + path,
            data=body,
            headers=headers,
            method=method,
        )
        opener = build_opener(HTTPSHandler(), _NoRedirect())
        try:
            with opener.open(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
                status = int(response.status)
        except HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except FacilitatorClientError:
            raise
        except Exception as exc:
            raise FacilitatorClientError("facilitator-runtime-http-failed") from exc
        if status < 200 or status >= 300:
            raise FacilitatorClientError(f"facilitator-runtime-http-status:{status}")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FacilitatorClientError("facilitator-runtime-json-invalid") from exc
        if not isinstance(result, dict):
            raise FacilitatorClientError("facilitator-runtime-response-not-object")
        return result

    def supported(self) -> dict[str, Any]:
        return self._request(method="GET", path="/supported")

    def verify(self, payment_payload: dict[str, Any], requirement: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            method="POST",
            path="/verify",
            payload={
                "paymentPayload": payment_payload,
                "paymentRequirements": requirement,
            },
        )

    def settle(self, payment_payload: dict[str, Any], requirement: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            method="POST",
            path="/settle",
            payload={
                "paymentPayload": payment_payload,
                "paymentRequirements": requirement,
            },
        )


def supports_exact_scope(
    supported: dict[str, Any],
    *,
    x402_version: int,
    network: str,
) -> bool:
    kinds = supported.get("kinds")
    candidates: list[dict[str, Any]] = []
    if isinstance(kinds, list):
        candidates = [item for item in kinds if isinstance(item, dict)]
    elif isinstance(kinds, dict):
        versioned = kinds.get(str(x402_version), [])
        if isinstance(versioned, list):
            candidates = [item for item in versioned if isinstance(item, dict)]
    for item in candidates:
        version = item.get("x402Version", x402_version)
        if int(version) == x402_version and item.get("scheme") == "exact" and item.get("network") == network:
            return True
    return False
