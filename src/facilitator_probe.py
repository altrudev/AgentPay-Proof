from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import socket
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from src.facilitator_admission import FacilitatorProbeEvidence


class FacilitatorProbeError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def http_error_301(self, req, fp, code, msg, headers):
        raise FacilitatorProbeError("facilitator-probe-redirect")
    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


@dataclass(frozen=True)
class FacilitatorProbeTarget:
    facilitator_id: str
    verify_url: str
    settle_url: str

    @property
    def host(self) -> str:
        verify = urlsplit(self.verify_url)
        settle = urlsplit(self.settle_url)
        if verify.scheme != "https" or settle.scheme != "https":
            raise FacilitatorProbeError("facilitator-probe-https-required")
        if not verify.hostname or verify.hostname != settle.hostname:
            raise FacilitatorProbeError("facilitator-probe-host-mismatch")
        if verify.username or verify.password or settle.username or settle.password:
            raise FacilitatorProbeError("facilitator-probe-userinfo-forbidden")
        return verify.hostname.lower()


def _dns_addresses(host: str) -> tuple[str, ...]:
    try:
        values = {
            item[4][0]
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if item and item[4]
        }
    except OSError as exc:
        raise FacilitatorProbeError("facilitator-probe-dns-failed") from exc
    if not values:
        raise FacilitatorProbeError("facilitator-probe-dns-empty")
    return tuple(sorted(values))


def _tls_observation(host: str, *, timeout: float) -> dict[str, str]:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert_der = tls.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError) as exc:
        raise FacilitatorProbeError("facilitator-probe-tls-failed") from exc
    if not cert_der:
        raise FacilitatorProbeError("facilitator-probe-certificate-missing")
    cert = x509.load_der_x509_certificate(cert_der)
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return {
        "tls_spki_sha256": "sha256:" + hashlib.sha256(spki).hexdigest(),
        "tls_cert_sha256": "sha256:" + hashlib.sha256(cert_der).hexdigest(),
        "tls_subject": cert.subject.rfc4514_string(),
        "tls_issuer": cert.issuer.rfc4514_string(),
    }


def _unauthenticated_post_status(url: str, *, timeout: float) -> int:
    request = Request(
        url,
        data=json.dumps({"probe": "frequency-auth-boundary"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AgentPay-Proof-Frequency-Probe/1",
        },
        method="POST",
    )
    opener = build_opener(HTTPSHandler(), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except FacilitatorProbeError:
        raise
    except Exception as exc:
        raise FacilitatorProbeError("facilitator-probe-http-failed") from exc


def probe_facilitator_transport(
    target: FacilitatorProbeTarget,
    *,
    observer: str,
    observed_at: int | None = None,
    timeout: float = 5.0,
) -> FacilitatorProbeEvidence:
    host = target.host
    dns = _dns_addresses(host)
    tls = _tls_observation(host, timeout=timeout)
    verify_status = _unauthenticated_post_status(target.verify_url, timeout=timeout)
    settle_status = _unauthenticated_post_status(target.settle_url, timeout=timeout)
    return FacilitatorProbeEvidence(
        facilitator_id=target.facilitator_id,
        verify_url=target.verify_url,
        settle_url=target.settle_url,
        resolved_host=host,
        resolved_addresses=dns,
        tls_spki_sha256=tls["tls_spki_sha256"],
        tls_cert_sha256=tls["tls_cert_sha256"],
        tls_subject=tls["tls_subject"],
        tls_issuer=tls["tls_issuer"],
        verify_unauthenticated_status=verify_status,
        settle_unauthenticated_status=settle_status,
        observer=observer,
        observed_at=int(time.time()) if observed_at is None else int(observed_at),
    )
