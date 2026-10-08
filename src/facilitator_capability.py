from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.facilitator_admission import FacilitatorCapabilityEvidence
from src.model import canonical_hash


class FacilitatorCapabilityError(RuntimeError):
    pass


def _supported_kinds(response: dict[str, Any], *, x402_version: int) -> tuple[tuple[str, str], ...]:
    kinds = response.get("kinds")
    raw: list[dict[str, Any]] = []
    if isinstance(kinds, list):
        raw = [item for item in kinds if isinstance(item, dict)]
    elif isinstance(kinds, dict):
        versioned = kinds.get(str(x402_version), [])
        if isinstance(versioned, list):
            raw = [item for item in versioned if isinstance(item, dict)]
    else:
        raise FacilitatorCapabilityError("facilitator-supported-kinds-invalid")

    parsed: set[tuple[str, str]] = set()
    for item in raw:
        version = item.get("x402Version", x402_version)
        try:
            version = int(version)
        except (TypeError, ValueError):
            continue
        scheme = str(item.get("scheme", "")).strip().lower()
        network = str(item.get("network", "")).strip().lower()
        if version == x402_version and scheme and network:
            parsed.add((scheme, network))
    if not parsed:
        raise FacilitatorCapabilityError("facilitator-supported-kinds-empty")
    return tuple(sorted(parsed))


def capability_evidence_from_supported(
    *,
    facilitator_id: str,
    supported_url: str,
    response: dict[str, Any],
    observer: str,
    observed_at: int,
    valid_until: int,
    x402_version: int = 2,
    authenticated: bool = True,
    access_model: str = "authenticated",
) -> FacilitatorCapabilityEvidence:
    kinds = _supported_kinds(response, x402_version=x402_version)
    schemes = tuple(sorted({scheme for scheme, _ in kinds}))
    networks = tuple(sorted({network for _, network in kinds}))
    return FacilitatorCapabilityEvidence(
        facilitator_id=facilitator_id,
        supported_url=supported_url,
        supported_response_digest=canonical_hash(response),
        schemes=schemes,
        networks=networks,
        authenticated=authenticated,
        observer=observer,
        observed_at=observed_at,
        valid_until=valid_until,
        access_model=access_model,
    )


def require_supported_scope(
    evidence: FacilitatorCapabilityEvidence,
    *,
    scheme: str,
    network: str,
) -> None:
    if scheme.lower() not in evidence.schemes:
        raise FacilitatorCapabilityError("facilitator-supported-scheme-missing")
    if network.lower() not in evidence.networks:
        raise FacilitatorCapabilityError("facilitator-supported-network-missing")
