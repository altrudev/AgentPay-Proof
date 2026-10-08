from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.provider_manifest import ProviderManifest


class ProviderManifestSigningError(RuntimeError):
    pass


def load_ed25519_private_key(path: str | Path) -> Ed25519PrivateKey:
    p = Path(path)
    try:
        mode = p.stat().st_mode & 0o777
    except OSError as exc:
        raise ProviderManifestSigningError("provider-manifest-key-unavailable") from exc
    if mode & 0o077:
        raise ProviderManifestSigningError("provider-manifest-key-permissions-too-open")
    try:
        key = serialization.load_pem_private_key(p.read_bytes(), password=None)
    except Exception as exc:
        raise ProviderManifestSigningError("provider-manifest-key-invalid") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ProviderManifestSigningError("provider-manifest-key-not-ed25519")
    return key


def public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def sign_provider_manifest(
    manifest: ProviderManifest,
    *,
    private_key: Ed25519PrivateKey,
) -> ProviderManifest:
    signature = private_key.sign(manifest.digest.encode("ascii"))
    return replace(manifest, signature=base64.b64encode(signature).decode("ascii"))
