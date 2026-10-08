from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import os
import secrets
import time
from typing import Callable

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


class CdpAuthError(RuntimeError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _json_b64(value: dict) -> str:
    return _b64url(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))


@dataclass(frozen=True)
class CdpApiKey:
    key_id: str
    secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.key_id.strip():
            raise ValueError("cdp-api-key-id-required")
        if not self.secret.strip():
            raise ValueError("cdp-api-key-secret-required")

    @classmethod
    def from_environment(
        cls,
        *,
        key_id_var: str = "CDP_API_KEY_ID",
        secret_var: str = "CDP_API_KEY_SECRET",
    ) -> "CdpApiKey":
        key_id = os.environ.get(key_id_var, "")
        secret = os.environ.get(secret_var, "")
        if not key_id or not secret:
            raise CdpAuthError("cdp-api-key-environment-unavailable")
        return cls(key_id=key_id, secret=secret)


def _load_private_key(secret: str):
    normalized = secret.replace("\\n", "\n")
    try:
        key = serialization.load_pem_private_key(normalized.encode("utf-8"), password=None)
        if isinstance(key, ec.EllipticCurvePrivateKey):
            return "ES256", key
    except Exception:
        pass

    try:
        decoded = base64.b64decode(normalized, validate=True)
        if len(decoded) == 64:
            return "EdDSA", ed25519.Ed25519PrivateKey.from_private_bytes(decoded[:32])
    except Exception:
        pass

    raise CdpAuthError("cdp-api-key-secret-format-unsupported")


def generate_cdp_jwt(
    api_key: CdpApiKey,
    *,
    method: str,
    host: str,
    path: str,
    now: int | None = None,
    expires_in: int = 120,
    nonce: str | None = None,
) -> str:
    method = str(method).upper()
    host = str(host).strip().lower()
    path = str(path).strip()
    if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
        raise CdpAuthError("cdp-jwt-method-invalid")
    if not host or "/" in host:
        raise CdpAuthError("cdp-jwt-host-invalid")
    if not path.startswith("/"):
        raise CdpAuthError("cdp-jwt-path-invalid")
    if expires_in <= 0 or expires_in > 120:
        raise CdpAuthError("cdp-jwt-expiry-outside-policy")

    algorithm, private_key = _load_private_key(api_key.secret)
    ts = int(time.time()) if now is None else int(now)
    header = {
        "alg": algorithm,
        "kid": api_key.key_id,
        "typ": "JWT",
        "nonce": nonce or "".join(secrets.choice("0123456789") for _ in range(16)),
    }
    claims = {
        "aud": None,
        "exp": ts + expires_in,
        "iss": "cdp",
        "nbf": ts,
        "sub": api_key.key_id,
        "uris": [f"{method} {host}{path}"],
    }
    signing_input = (_json_b64(header) + "." + _json_b64(claims)).encode("ascii")

    if algorithm == "EdDSA":
        signature = private_key.sign(signing_input)
    elif algorithm == "ES256":
        der = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        raise CdpAuthError("cdp-jwt-algorithm-unsupported")

    return signing_input.decode("ascii") + "." + _b64url(signature)


class CdpBearerTokenProvider:
    """Request-bound short-lived CDP JWT provider.

    Secret material remains inside the provider instance and is never returned
    except indirectly through the signed JWT token.
    """

    def __init__(
        self,
        api_key: CdpApiKey,
        *,
        expires_in: int = 120,
        clock: Callable[[], int] | None = None,
    ):
        if expires_in <= 0 or expires_in > 120:
            raise ValueError("cdp-token-expiry-outside-policy")
        self._api_key = api_key
        self._expires_in = expires_in
        self._clock = clock or (lambda: int(time.time()))

    def __call__(self, *, method: str, host: str, path: str) -> str:
        return generate_cdp_jwt(
            self._api_key,
            method=method,
            host=host,
            path=path,
            now=self._clock(),
            expires_in=self._expires_in,
        )
