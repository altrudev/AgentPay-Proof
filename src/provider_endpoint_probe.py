from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import socket
import ssl
import hashlib
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from src.model import canonical_hash
from src.provider_manifest import ProviderEvidence


PROVIDER_ENDPOINT_OBSERVATION_SCHEMA = "agentpay-provider-endpoint-observation/1"


class ProviderEndpointProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderEndpointObservation:
    provider_id: str
    base_url: str
    resolved_host: str
    resolved_addresses: tuple[str, ...]
    tls_spki_sha256: str
    tls_cert_sha256: str
    tls_subject: str
    tls_issuer: str
    health_document: dict[str, Any]
    identity_document: dict[str, Any]
    discovery_document: dict[str, Any]
    observed_at: int
    observer: str

    @property
    def digest(self) -> str:
        return canonical_hash({
            "schema": PROVIDER_ENDPOINT_OBSERVATION_SCHEMA,
            **asdict(self),
        })


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderEndpointProbeError("provider-endpoint-redirect")


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ProviderEndpointProbeError("provider-endpoint-url-invalid")
    if parsed.query or parsed.fragment:
        raise ProviderEndpointProbeError("provider-endpoint-url-invalid")
    port = parsed.port or 443
    if port != 443:
        raise ProviderEndpointProbeError("provider-endpoint-port-invalid")
    return parsed.scheme, parsed.hostname.lower(), port


def _get_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "AgentPay-Frequency-Provider-Probe/1"})
    try:
        opener = build_opener(HTTPSHandler(), _NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            if int(response.status) != 200:
                raise ProviderEndpointProbeError(f"provider-endpoint-http-status:{response.status}")
            raw = response.read()
    except HTTPError as exc:
        raise ProviderEndpointProbeError(f"provider-endpoint-http-status:{exc.code}") from exc
    except ProviderEndpointProbeError:
        raise
    except Exception as exc:
        raise ProviderEndpointProbeError("provider-endpoint-http-failed") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ProviderEndpointProbeError("provider-endpoint-json-invalid") from exc
    if not isinstance(value, dict):
        raise ProviderEndpointProbeError("provider-endpoint-json-not-object")
    return value


def _transport(host: str, *, timeout: float) -> tuple[tuple[str, ...], dict[str, str]]:
    try:
        addresses = tuple(sorted({
            item[4][0]
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if item and item[4]
        }))
    except OSError as exc:
        raise ProviderEndpointProbeError("provider-endpoint-dns-failed") from exc
    if not addresses:
        raise ProviderEndpointProbeError("provider-endpoint-dns-empty")
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert_der = tls.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError) as exc:
        raise ProviderEndpointProbeError("provider-endpoint-tls-failed") from exc
    if not cert_der:
        raise ProviderEndpointProbeError("provider-endpoint-certificate-missing")
    cert = x509.load_der_x509_certificate(cert_der)
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return addresses, {
        "tls_spki_sha256": "sha256:" + hashlib.sha256(spki).hexdigest(),
        "tls_cert_sha256": "sha256:" + hashlib.sha256(cert_der).hexdigest(),
        "tls_subject": cert.subject.rfc4514_string(),
        "tls_issuer": cert.issuer.rfc4514_string(),
    }


def probe_provider_endpoint(
    *,
    provider_id: str,
    base_url: str,
    service_id: str,
    observer: str,
    observed_at: int,
    timeout: float = 8.0,
) -> ProviderEndpointObservation:
    parsed = urlsplit(base_url)
    if parsed.path not in {"", "/"}:
        raise ProviderEndpointProbeError("provider-endpoint-base-url-invalid")
    try:
        _, host, _ = _origin(base_url)
    except ProviderEndpointProbeError as exc:
        raise ProviderEndpointProbeError("provider-endpoint-base-url-invalid") from exc
    addresses, tls = _transport(host, timeout=timeout)
    root = base_url.rstrip("/")
    health = _get_json(root + "/api/health", timeout=timeout)
    identity = _get_json(root + "/api/provider/identity", timeout=timeout)
    discovery = _get_json(root + f"/api/discovery?service_id={service_id}", timeout=timeout)

    if health.get("ok") is not True or health.get("live_enabled") is not True:
        raise ProviderEndpointProbeError("provider-endpoint-health-not-live")
    if identity.get("provider_id") != provider_id:
        raise ProviderEndpointProbeError("provider-endpoint-identity-mismatch")
    if identity.get("domain") != host:
        raise ProviderEndpointProbeError("provider-endpoint-domain-mismatch")
    if discovery.get("service_id") != service_id:
        raise ProviderEndpointProbeError("provider-endpoint-service-mismatch")

    return ProviderEndpointObservation(
        provider_id=provider_id,
        base_url=root,
        resolved_host=host,
        resolved_addresses=addresses,
        tls_spki_sha256=tls["tls_spki_sha256"],
        tls_cert_sha256=tls["tls_cert_sha256"],
        tls_subject=tls["tls_subject"],
        tls_issuer=tls["tls_issuer"],
        health_document=health,
        identity_document=identity,
        discovery_document=discovery,
        observed_at=observed_at,
        observer=observer,
    )


def identity_control_evidence(
    observation: ProviderEndpointObservation,
    *,
    expires_at: int,
) -> ProviderEvidence:
    return ProviderEvidence(
        evidence_type="identity-control",
        subject=observation.provider_id,
        issuer=observation.observer,
        reference=observation.base_url + "/api/provider/identity",
        observed_at=observation.observed_at,
        expires_at=expires_at,
        digest=canonical_hash({
            "schema": "agentpay-provider-identity-control-observation/1",
            "observation_digest": observation.digest,
            "identity_document_digest": canonical_hash(observation.identity_document),
        }),
        details={"observation": asdict(observation)},
    )


def endpoint_control_evidence(
    observation: ProviderEndpointObservation,
    *,
    adapter_id: str,
    expires_at: int,
) -> ProviderEvidence:
    try:
        if _origin(adapter_id) != _origin(observation.base_url):
            raise ProviderEndpointProbeError("provider-endpoint-adapter-outside-observed-origin")
    except ProviderEndpointProbeError as exc:
        if str(exc) == "provider-endpoint-adapter-outside-observed-origin":
            raise
        raise ProviderEndpointProbeError("provider-endpoint-adapter-outside-observed-origin") from exc
    return ProviderEvidence(
        evidence_type="endpoint-control",
        subject=observation.provider_id,
        issuer=observation.observer,
        reference=adapter_id,
        observed_at=observation.observed_at,
        expires_at=expires_at,
        digest=canonical_hash({
            "schema": "agentpay-provider-endpoint-control-observation/1",
            "observation_digest": observation.digest,
            "adapter_id": adapter_id,
            "tls_spki_sha256": observation.tls_spki_sha256,
        }),
        details={"observation": asdict(observation)},
    )
