from __future__ import annotations

from dataclasses import asdict, dataclass
import secrets
from typing import Callable
from urllib.parse import urlsplit

from src.model import canonical_hash
from src.provider_manifest import ProviderEvidence


RECIPIENT_CHALLENGE_SCHEMA = "agentpay-provider-recipient-challenge/1"
RECIPIENT_PROOF_SCHEMA = "agentpay-provider-recipient-proof/1"


class ProviderRecipientProofError(RuntimeError):
    pass


def _address(value: str) -> str:
    value = str(value).strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError("provider-recipient-address-invalid")
    int(value[2:], 16)
    return value


@dataclass(frozen=True)
class RecipientControlChallenge:
    provider_id: str
    recipient: str
    chain_id: int
    domain: str
    endpoint: str
    quote_digest: str
    nonce: str
    issued_at: int
    expires_at: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", str(self.provider_id).strip())
        object.__setattr__(self, "recipient", _address(self.recipient))
        object.__setattr__(self, "domain", str(self.domain).strip().lower())
        object.__setattr__(self, "endpoint", str(self.endpoint).strip())
        object.__setattr__(self, "quote_digest", str(self.quote_digest).strip().lower())
        object.__setattr__(self, "nonce", str(self.nonce).strip().lower())
        if not self.provider_id:
            raise ValueError("provider-recipient-provider-required")
        if self.chain_id <= 0:
            raise ValueError("provider-recipient-chain-invalid")
        if not self.domain or "." not in self.domain:
            raise ValueError("provider-recipient-domain-invalid")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname.lower() != self.domain
            or parsed.username
            or parsed.password
            or parsed.fragment
            or (parsed.port not in {None, 443})
        ):
            raise ValueError("provider-recipient-endpoint-invalid")
        if not self.quote_digest:
            raise ValueError("provider-recipient-quote-digest-required")
        if not self.nonce or len(self.nonce) < 32:
            raise ValueError("provider-recipient-nonce-invalid")
        if self.issued_at < 0 or self.expires_at <= self.issued_at:
            raise ValueError("provider-recipient-validity-invalid")
        if self.expires_at - self.issued_at > 900:
            raise ValueError("provider-recipient-validity-too-long")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": RECIPIENT_CHALLENGE_SCHEMA, **asdict(self)})

    @property
    def message(self) -> str:
        return (
            "AgentPay Provider Recipient Control\n"
            f"Provider: {self.provider_id}\n"
            f"Recipient: {self.recipient}\n"
            f"Chain ID: {self.chain_id}\n"
            f"Domain: {self.domain}\n"
            f"Endpoint: {self.endpoint}\n"
            f"Quote digest: {self.quote_digest}\n"
            f"Nonce: {self.nonce}\n"
            f"Issued at: {self.issued_at}\n"
            f"Expires at: {self.expires_at}\n"
            f"Challenge digest: {self.digest}\n"
            "Purpose: prove control of this payment recipient only; this is not a payment authorization."
        )


@dataclass(frozen=True)
class RecipientControlProof:
    challenge_digest: str
    recipient: str
    signature: str
    recovered_address: str
    verified_at: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipient", _address(self.recipient))
        object.__setattr__(self, "recovered_address", _address(self.recovered_address))
        if not str(self.challenge_digest).strip():
            raise ValueError("provider-recipient-challenge-digest-required")
        if not str(self.signature).startswith("0x"):
            raise ValueError("provider-recipient-signature-invalid")
        if self.verified_at < 0:
            raise ValueError("provider-recipient-proof-time-invalid")

    @property
    def digest(self) -> str:
        return canonical_hash({
            "schema": RECIPIENT_PROOF_SCHEMA,
            **asdict(self),
        })


def new_recipient_challenge(
    *,
    provider_id: str,
    recipient: str,
    chain_id: int,
    domain: str,
    endpoint: str,
    quote_digest: str,
    now: int,
    ttl_seconds: int = 600,
    nonce: str | None = None,
) -> RecipientControlChallenge:
    if ttl_seconds <= 0 or ttl_seconds > 900:
        raise ValueError("provider-recipient-ttl-invalid")
    return RecipientControlChallenge(
        provider_id=provider_id,
        recipient=recipient,
        chain_id=chain_id,
        domain=domain,
        endpoint=endpoint,
        quote_digest=quote_digest,
        nonce=nonce or secrets.token_hex(32),
        issued_at=now,
        expires_at=now + ttl_seconds,
    )


def recover_eip191_address(message: str, signature: str) -> str:
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError as exc:
        raise ProviderRecipientProofError("provider-recipient-eth-account-unavailable") from exc

    try:
        return _address(Account.recover_message(encode_defunct(text=message), signature=signature))
    except Exception as exc:
        raise ProviderRecipientProofError("provider-recipient-signature-recovery-failed") from exc


def verify_recipient_signature(
    challenge: RecipientControlChallenge,
    *,
    signature: str,
    now: int,
    recover_address: Callable[[str, str], str] = recover_eip191_address,
) -> RecipientControlProof:
    if now < challenge.issued_at:
        raise ProviderRecipientProofError("provider-recipient-challenge-not-yet-valid")
    if now > challenge.expires_at:
        raise ProviderRecipientProofError("provider-recipient-challenge-expired")

    recovered = _address(recover_address(challenge.message, signature))
    if recovered != challenge.recipient:
        raise ProviderRecipientProofError("provider-recipient-signer-mismatch")

    return RecipientControlProof(
        challenge_digest=challenge.digest,
        recipient=challenge.recipient,
        signature=signature,
        recovered_address=recovered,
        verified_at=now,
    )


def recipient_provider_evidence(
    challenge: RecipientControlChallenge,
    proof: RecipientControlProof,
    *,
    issuer: str,
    expires_at: int,
) -> ProviderEvidence:
    if proof.challenge_digest != challenge.digest:
        raise ProviderRecipientProofError("provider-recipient-proof-challenge-mismatch")
    if proof.recipient != challenge.recipient or proof.recovered_address != challenge.recipient:
        raise ProviderRecipientProofError("provider-recipient-proof-address-mismatch")
    if expires_at <= proof.verified_at:
        raise ValueError("provider-recipient-evidence-expiry-invalid")
    return ProviderEvidence(
        evidence_type="recipient-control",
        subject=challenge.provider_id,
        issuer=issuer,
        reference=challenge.recipient,
        observed_at=proof.verified_at,
        expires_at=expires_at,
        digest=proof.digest,
        details={
            "challenge": asdict(challenge),
            "proof": asdict(proof),
        },
    )
