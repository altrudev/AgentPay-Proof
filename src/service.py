from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import re
import time
import uuid

from src.demo import USDC_BASE
from src.model import BASE_CHAIN_ID, Quote, ServiceResult, canonical_hash

DEFAULT_SERVICE_ID = "code-analysis-v1"
SERVICE_ID = DEFAULT_SERVICE_ID  # Backward-compatible alias.
DEFAULT_PRICE_ATOMIC = 250_000
QUOTE_TTL_SECONDS = 300

SERVICE_SPECS = {
    "code-analysis-v1": {
        "slug": "code",
        "title": "Code Analysis",
        "description": "Deterministic security and quality scan with a verifiable report.",
        "price_atomic": 250_000,
        "input_label": "Code or configuration",
        "input_placeholder": "Paste a small code/configuration sample to analyze…",
        "tags": ["AI", "Security"],
    },
    "data-research-v1": {
        "slug": "research",
        "title": "Data Research",
        "description": "Deterministic summarization and keyword extraction for supplied public text.",
        "price_atomic": 350_000,
        "input_label": "Research material",
        "input_placeholder": "Paste public text or notes to summarize…",
        "tags": ["Analysis", "Data"],
    },
    "3d-generation-v1": {
        "slug": "3d",
        "title": "3D Generation",
        "description": "Deterministic parametric OBJ artifact generated from a bounded text request.",
        "price_atomic": 500_000,
        "input_label": "3D request",
        "input_placeholder": "Describe the object label or bounded 3D request…",
        "tags": ["Creative", "3D"],
    },
}

_SLUG_TO_ID = {spec["slug"]: service_id for service_id, spec in SERVICE_SPECS.items()}


def resolve_service_id(value: str | None) -> str:
    raw = (value or DEFAULT_SERVICE_ID).strip()
    service_id = _SLUG_TO_ID.get(raw, raw)
    if service_id not in SERVICE_SPECS:
        raise ValueError("service-unknown")
    return service_id


def service_catalog() -> list[dict]:
    return [
        {"service_id": service_id, **spec}
        for service_id, spec in SERVICE_SPECS.items()
    ]


@dataclass(frozen=True)
class ServiceRequest:
    document: str
    service_id: str = DEFAULT_SERVICE_ID

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_id", resolve_service_id(self.service_id))
        if not self.document.strip():
            raise ValueError("document-required")

    @property
    def digest(self) -> str:
        return canonical_hash({"service_id": self.service_id, "document": self.document})


def create_quote(
    request: ServiceRequest,
    *,
    now: int | None = None,
    amount_atomic: int | None = None,
    recipient: str = "0x000000000000000000000000000000000000BEEF",
    chain_id: int = BASE_CHAIN_ID,
    asset_contract: str = USDC_BASE,
) -> Quote:
    now = int(time.time()) if now is None else now
    spec = SERVICE_SPECS[request.service_id]
    price = spec["price_atomic"] if amount_atomic is None else amount_atomic
    return Quote(
        quote_id=f"q-{uuid.uuid4()}",
        service_id=request.service_id,
        recipient=recipient,
        chain_id=chain_id,
        asset_contract=asset_contract,
        amount_atomic=price,
        expires_at=now + QUOTE_TTL_SECONDS,
        request_digest=request.digest,
    )


def _code_analysis(document: str) -> dict:
    lines = document.splitlines() or [document]
    patterns = [
        ("dynamic-eval", r"\beval\s*\("),
        ("shell-exec", r"\b(os\.system|subprocess\.|shell\s*=\s*True)"),
        ("hardcoded-secret", r"(?i)\b(password|api[_-]?key|secret|token)\b\s*[:=]\s*['\"][^'\"]+"),
        ("todo-marker", r"(?i)\b(TODO|FIXME|HACK)\b"),
    ]
    findings = []
    for finding_id, pattern in patterns:
        count = len(re.findall(pattern, document))
        if count:
            findings.append({"id": finding_id, "count": count})
    return {
        "service_id": "code-analysis-v1",
        "line_count": len(lines),
        "character_count": len(document),
        "finding_count": sum(item["count"] for item in findings),
        "findings": findings,
        "source_digest": canonical_hash(document),
    }


def _data_research(document: str) -> dict:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", document.strip()) if s.strip()]
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", document.lower())
    stop = {
        "the", "and", "for", "that", "with", "this", "from", "are", "was", "were",
        "have", "has", "had", "but", "not", "you", "your", "into", "their", "they",
    }
    counts = Counter(word for word in words if word not in stop)
    keywords = [word for word, _ in counts.most_common(8)]
    return {
        "service_id": "data-research-v1",
        "summary": " ".join(sentences[:2]) if sentences else document[:320],
        "keywords": keywords,
        "sentence_count": len(sentences),
        "source_digest": canonical_hash(document),
    }


def _obj_artifact(document: str) -> dict:
    # Small deterministic cube OBJ: a real portable 3D artifact without an
    # external model dependency. The request labels the artifact but cannot
    # inject executable content.
    label = re.sub(r"[^A-Za-z0-9 _-]+", "", document).strip()[:48] or "AgentPay Cube"
    obj = "\n".join([
        f"# {label}",
        "o AgentPayCube",
        "v -0.5 -0.5 -0.5", "v 0.5 -0.5 -0.5", "v 0.5 0.5 -0.5", "v -0.5 0.5 -0.5",
        "v -0.5 -0.5 0.5", "v 0.5 -0.5 0.5", "v 0.5 0.5 0.5", "v -0.5 0.5 0.5",
        "f 1 2 3 4", "f 5 8 7 6", "f 1 5 6 2", "f 2 6 7 3", "f 3 7 8 4", "f 5 1 4 8",
        "",
    ])
    return {
        "service_id": "3d-generation-v1",
        "format": "obj",
        "filename": "agentpay-cube.obj",
        "label": label,
        "vertex_count": 8,
        "face_count": 6,
        "obj": obj,
        "source_digest": canonical_hash(document),
    }


def execute(
    request: ServiceRequest,
    quote: Quote,
    *,
    now: int | None = None,
) -> tuple[dict, ServiceResult]:
    now = int(time.time()) if now is None else now
    if quote.service_id != request.service_id:
        raise PermissionError("service-binding-mismatch")
    if quote.request_digest != request.digest:
        raise PermissionError("request-binding-mismatch")
    if now > quote.expires_at:
        raise PermissionError("quote-expired")

    if request.service_id == "code-analysis-v1":
        artifact = _code_analysis(request.document)
    elif request.service_id == "data-research-v1":
        artifact = _data_research(request.document)
    elif request.service_id == "3d-generation-v1":
        artifact = _obj_artifact(request.document)
    else:  # resolve_service_id() should make this unreachable.
        raise PermissionError("service-unsupported")

    result = ServiceResult(
        request.service_id,
        request.digest,
        canonical_hash(artifact),
        "COMPLETE",
    )
    return artifact, result
