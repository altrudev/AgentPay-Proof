from __future__ import annotations

import base64
from dataclasses import dataclass, asdict
import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from src.model import canonical_hash


class X402ResourceProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class X402ResourceQuoteEvidence:
    resource_url: str
    request_digest: str
    payment_required: dict[str, Any]
    payment_required_digest: str
    observed_at: int
    observer: str

    @property
    def digest(self) -> str:
        return canonical_hash({
            "schema": "agentpay-x402-resource-quote-evidence/1",
            **asdict(self),
        })


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise X402ResourceProbeError("x402-resource-probe-redirect")


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or (parsed.port not in {None, 443})
    ):
        raise X402ResourceProbeError("x402-resource-probe-url-invalid")
    return parsed.scheme, parsed.hostname.lower(), parsed.port or 443


def decode_payment_required_header(value: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        raise X402ResourceProbeError("x402-payment-required-header-missing")
    raw = value.strip()
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(raw, validate=True)
        parsed = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise X402ResourceProbeError("x402-payment-required-header-invalid") from exc
    if not isinstance(parsed, dict) or parsed.get("x402Version") != 2:
        raise X402ResourceProbeError("x402-payment-required-v2-invalid")
    if not isinstance(parsed.get("accepts"), list) or not parsed["accepts"]:
        raise X402ResourceProbeError("x402-payment-required-accepts-missing")
    return parsed


def probe_x402_resource(
    *,
    resource_url: str,
    request_body: dict[str, Any],
    observer: str,
    observed_at: int,
    timeout: float = 8.0,
) -> X402ResourceQuoteEvidence:
    expected_origin = _origin(resource_url)
    body = json.dumps(request_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = Request(
        resource_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AgentPay-Proof-Frequency-Quote-Probe/1",
        },
        method="POST",
    )
    try:
        opener = build_opener(HTTPSHandler(), _NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            status = int(response.status)
            header = response.headers.get("payment-required")
    except HTTPError as exc:
        status = int(exc.code)
        header = exc.headers.get("payment-required")
    except Exception as exc:
        raise X402ResourceProbeError("x402-resource-probe-http-failed") from exc

    if status != 402:
        raise X402ResourceProbeError(f"x402-resource-probe-status:{status}")
    payment_required = decode_payment_required_header(header)
    resource = payment_required.get("resource")
    if not isinstance(resource, dict) or not isinstance(resource.get("url"), str):
        raise X402ResourceProbeError("x402-resource-probe-resource-binding-missing")
    if _origin(resource["url"]) != expected_origin:
        raise X402ResourceProbeError("x402-resource-probe-resource-origin-mismatch")
    return X402ResourceQuoteEvidence(
        resource_url=resource_url,
        request_digest=canonical_hash(request_body),
        payment_required=payment_required,
        payment_required_digest=canonical_hash(payment_required),
        observed_at=observed_at,
        observer=observer,
    )
