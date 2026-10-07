from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
import json
import sqlite3
from pathlib import Path
from typing import Mapping

from src.provider_admission import ProviderAdmission, ProviderBinding, ProviderRegistry, evaluate_provider_binding
from src.provider_manifest import ProviderEvidence, ProviderManifest, SignatureVerifier, verify_provider_manifest


class ProviderStoreError(RuntimeError):
    pass


class ProviderRegistryStore:
    """Durable provider onboarding and revocation journal.

    Only a cryptographically verified manifest whose ProviderBinding also
    passes admission policy is persisted as ACTIVE. Every replacement must use
    a strictly increasing binding version. Revocation is durable and fail-closed.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_registry (
                    provider_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    manifest_digest TEXT NOT NULL,
                    binding_digest TEXT NOT NULL,
                    admission_digest TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    admission_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    revoked_at INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_registry_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    manifest_digest TEXT,
                    binding_digest TEXT,
                    admission_digest TEXT,
                    recorded_at INTEGER NOT NULL
                )
                """
            )

    def admit_manifest(
        self,
        manifest: ProviderManifest,
        *,
        now: int,
        signature_verifier: SignatureVerifier | None,
        trusted_issuers: Mapping[str, str],
        evidence_verifiers: Mapping[str, object] | None = None,
    ) -> tuple[ProviderManifest, ProviderAdmission]:
        verification = verify_provider_manifest(
            manifest,
            now=now,
            signature_verifier=signature_verifier,
            trusted_issuers=trusted_issuers,
            evidence_verifiers=evidence_verifiers,
        )
        if verification.verdict != "VERIFIED":
            raise ProviderStoreError("provider-manifest-not-verified:" + ",".join(verification.reasons))

        admission = evaluate_provider_binding(manifest.binding, now=now)
        if admission.decision != "ADMIT":
            raise ProviderStoreError("provider-binding-not-admitted:" + ",".join(admission.reasons))

        manifest_json = json.dumps(
            {
                "manifest_id": manifest.manifest_id,
                "provider_id": manifest.provider_id,
                "binding": asdict(manifest.binding),
                "issuer_key_id": manifest.issuer_key_id,
                "signature": manifest.signature,
                "evidence": [asdict(item) for item in manifest.evidence],
                "issued_at": manifest.issued_at,
                "expires_at": manifest.expires_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        admission_json = json.dumps(asdict(admission), sort_keys=True, separators=(",", ":"))

        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT version,state FROM provider_registry WHERE provider_id = ?",
                (manifest.provider_id,),
            ).fetchone()
            if row is not None and manifest.binding.version <= int(row["version"]):
                raise ProviderStoreError("provider-version-not-monotonic")
            if row is not None:
                previous = conn.execute(
                    "SELECT manifest_json FROM provider_registry WHERE provider_id = ?",
                    (manifest.provider_id,),
                ).fetchone()
                previous_manifest = json.loads(previous["manifest_json"])
                if previous_manifest.get("issuer_key_id") != manifest.issuer_key_id:
                    raise ProviderStoreError("provider-key-rotation-not-authorized")
            conn.execute(
                """
                INSERT INTO provider_registry(
                    provider_id,version,state,manifest_digest,binding_digest,
                    admission_digest,manifest_json,admission_json,updated_at,revoked_at
                ) VALUES (?,?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(provider_id) DO UPDATE SET
                    version=excluded.version,
                    state='ACTIVE',
                    manifest_digest=excluded.manifest_digest,
                    binding_digest=excluded.binding_digest,
                    admission_digest=excluded.admission_digest,
                    manifest_json=excluded.manifest_json,
                    admission_json=excluded.admission_json,
                    updated_at=excluded.updated_at,
                    revoked_at=NULL
                """,
                (
                    manifest.provider_id,
                    manifest.binding.version,
                    "ACTIVE",
                    manifest.digest,
                    manifest.binding.digest,
                    admission.digest,
                    manifest_json,
                    admission_json,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO provider_registry_history(
                    provider_id,version,event,manifest_digest,binding_digest,admission_digest,recorded_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    manifest.provider_id,
                    manifest.binding.version,
                    "ADMITTED",
                    manifest.digest,
                    manifest.binding.digest,
                    admission.digest,
                    now,
                ),
            )
        return manifest, admission

    def revoke(self, provider_id: str, *, now: int) -> None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT version,state,manifest_digest,binding_digest,admission_digest FROM provider_registry WHERE provider_id = ?",
                (provider_id,),
            ).fetchone()
            if row is None or row["state"] != "ACTIVE":
                raise ProviderStoreError("provider-not-active")
            changed = conn.execute(
                "UPDATE provider_registry SET state='REVOKED', revoked_at=?, updated_at=? WHERE provider_id=? AND state='ACTIVE'",
                (now, now, provider_id),
            ).rowcount
            if changed != 1:
                raise ProviderStoreError("provider-revocation-race")
            conn.execute(
                """
                INSERT INTO provider_registry_history(
                    provider_id,version,event,manifest_digest,binding_digest,admission_digest,recorded_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    provider_id,
                    row["version"],
                    "REVOKED",
                    row["manifest_digest"],
                    row["binding_digest"],
                    row["admission_digest"],
                    now,
                ),
            )

    def load_registry(
        self,
        *,
        now: int,
        signature_verifier: SignatureVerifier | None,
        trusted_issuers: Mapping[str, str],
        evidence_verifiers: Mapping[str, object] | None = None,
    ) -> ProviderRegistry:
        registry = ProviderRegistry()
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT manifest_digest,binding_digest,admission_digest,manifest_json,admission_json FROM provider_registry WHERE state='ACTIVE' ORDER BY provider_id"
            ).fetchall()
        for row in rows:
            raw_manifest = json.loads(row["manifest_json"])
            binding = ProviderBinding(**raw_manifest["binding"])
            evidence = tuple(ProviderEvidence(**item) for item in raw_manifest["evidence"])
            manifest = ProviderManifest(
                manifest_id=raw_manifest["manifest_id"],
                provider_id=raw_manifest["provider_id"],
                binding=binding,
                issuer_key_id=raw_manifest["issuer_key_id"],
                signature=raw_manifest["signature"],
                evidence=evidence,
                issued_at=raw_manifest["issued_at"],
                expires_at=raw_manifest["expires_at"],
            )
            stored_admission = ProviderAdmission(**json.loads(row["admission_json"]))
            if manifest.digest != row["manifest_digest"]:
                raise ProviderStoreError("persisted-provider-manifest-digest-mismatch")
            if binding.digest != row["binding_digest"]:
                raise ProviderStoreError("persisted-provider-binding-row-mismatch")
            if stored_admission.digest != row["admission_digest"]:
                raise ProviderStoreError("persisted-provider-admission-digest-mismatch")
            if now > min(manifest.expires_at, binding.valid_until, stored_admission.valid_until):
                continue
            verification = verify_provider_manifest(
                manifest, now=now, signature_verifier=signature_verifier,
                trusted_issuers=trusted_issuers, evidence_verifiers=evidence_verifiers,
            )
            if verification.verdict != "VERIFIED":
                raise ProviderStoreError("persisted-provider-manifest-not-verified")
            current_policy = evaluate_provider_binding(binding, now=now)
            if current_policy.decision != "ADMIT":
                raise ProviderStoreError("persisted-provider-no-longer-admissible")
            if current_policy.binding_digest != stored_admission.binding_digest:
                raise ProviderStoreError("persisted-provider-binding-mismatch")
            registry.restore(binding, stored_admission)
        return registry

    def status(self, provider_id: str) -> dict:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT provider_id,version,state,manifest_digest,binding_digest,admission_digest,updated_at,revoked_at FROM provider_registry WHERE provider_id=?",
                (provider_id,),
            ).fetchone()
        if row is None:
            raise ProviderStoreError("provider-not-found")
        return dict(row)
