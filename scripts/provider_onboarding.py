#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from src.provider_evidence_verifiers import PROVIDER_EVIDENCE_VERIFIERS
from src.provider_manifest import (
    ed25519_verify,
    provider_manifest_from_document,
)
from src.provider_onboarding import (
    build_signed_provider_manifest,
    create_provider_recipient_challenge,
    manifest_document,
)
from src.provider_profile import (
    AGENTPAY_PROVIDER_KEY_ID,
    AGENTPAY_PROVIDER_PUBLIC_KEY_B64,
)
from src.provider_recipient_proof import RecipientControlChallenge
from src.provider_registry_store import ProviderRegistryStore


def write_json(value: dict, path: str | None) -> None:
    data = json.dumps(value, sort_keys=True, indent=2) + "\n"
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
    else:
        print(data, end="")


def command_challenge(args) -> int:
    now = int(time.time())
    challenge = create_provider_recipient_challenge(
        now=now, ttl_seconds=args.ttl
    )
    write_json(
        {
            "challenge": asdict(challenge),
            "challenge_digest": challenge.digest,
            "message": challenge.message,
        },
        args.out,
    )
    return 0


def command_build(args) -> int:
    raw = json.loads(Path(args.challenge).read_text(encoding="utf-8"))
    challenge_raw = raw.get("challenge", raw)
    challenge = RecipientControlChallenge(**challenge_raw)
    signature = (
        Path(args.signature_file).read_text(encoding="utf-8").strip()
        if args.signature_file
        else str(args.signature or "").strip()
    )
    if not signature:
        raise SystemExit("recipient signature is required")
    now = int(time.time())
    manifest = build_signed_provider_manifest(
        recipient_signature=signature,
        challenge=challenge,
        now=now,
        version=args.version,
        signing_key_path=args.signing_key,
        observer=args.observer,
    )
    write_json(manifest_document(manifest), args.out)
    return 0


def command_admit(args) -> int:
    raw = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    raw.pop("manifest_digest", None)
    manifest = provider_manifest_from_document(raw)
    now = int(time.time())
    store = ProviderRegistryStore(args.registry)
    _, admission = store.admit_manifest(
        manifest,
        now=now,
        signature_verifier=ed25519_verify,
        trusted_issuers={
            AGENTPAY_PROVIDER_KEY_ID: AGENTPAY_PROVIDER_PUBLIC_KEY_B64
        },
        evidence_verifiers=PROVIDER_EVIDENCE_VERIFIERS,
    )
    write_json(
        {
            "provider_id": admission.provider_id,
            "decision": admission.decision,
            "binding_digest": admission.binding_digest,
            "admission_digest": admission.digest,
            "valid_until": admission.valid_until,
            "registry": str(Path(args.registry)),
        },
        args.out,
    )
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DDC/Frequency provider onboarding: challenge, build signed manifest, admit."
    )
    sub = p.add_subparsers(dest="command", required=True)

    challenge = sub.add_parser("challenge")
    challenge.add_argument("--ttl", type=int, default=600)
    challenge.add_argument("--out")
    challenge.set_defaults(func=command_challenge)

    build = sub.add_parser("build")
    build.add_argument("--challenge", required=True)
    sig = build.add_mutually_exclusive_group(required=True)
    sig.add_argument("--signature")
    sig.add_argument("--signature-file")
    build.add_argument("--signing-key", required=True)
    build.add_argument("--version", type=int, required=True)
    build.add_argument(
        "--observer", default="frequency:prometheus-provider-observer"
    )
    build.add_argument("--out", required=True)
    build.set_defaults(func=command_build)

    admit = sub.add_parser("admit")
    admit.add_argument("--manifest", required=True)
    admit.add_argument("--registry", required=True)
    admit.add_argument("--out")
    admit.set_defaults(func=command_admit)
    return p


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
