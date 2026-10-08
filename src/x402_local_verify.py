from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from src.model import canonical_hash
from src.settlement import JsonRpcClient
from src.x402 import EIP3009Authorization, X402Requirement, eip712_typed_data, encode_transfer_with_authorization_calldata, validate_signature


BALANCE_OF_SELECTOR = "70a08231"
AUTHORIZATION_STATE_SELECTOR = "e94a0102"


class X402LocalVerifyError(RuntimeError):
    pass


def _word_address(address: str) -> str:
    value = address.lower().removeprefix("0x")
    if len(value) != 40:
        raise ValueError("x402-local-address-invalid")
    int(value, 16)
    return value.rjust(64, "0")


def _word_bytes32(value: str) -> str:
    raw = value.lower().removeprefix("0x")
    if len(raw) != 64:
        raise ValueError("x402-local-bytes32-invalid")
    int(raw, 16)
    return raw


def _rpc_int(value: str | int | None, code: str) -> int:
    if value is None:
        raise X402LocalVerifyError(code)
    try:
        return int(value, 16) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as exc:
        raise X402LocalVerifyError(code) from exc


def recover_eip712_address(
    requirement: X402Requirement,
    authorization: EIP3009Authorization,
    signature: str,
) -> str:
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data
    except ImportError as exc:
        raise X402LocalVerifyError("x402-local-eth-account-unavailable") from exc
    try:
        signable = encode_typed_data(full_message=eip712_typed_data(requirement, authorization))
        return str(Account.recover_message(signable, signature=signature)).lower()
    except Exception as exc:
        raise X402LocalVerifyError("x402-local-signature-recovery-failed") from exc


@dataclass(frozen=True)
class LocalAuthorizationVerification:
    payer: str
    recipient: str
    amount: int
    asset: str
    network: str
    nonce: str
    balance_atomic: int
    authorization_used: bool
    transfer_simulation_ok: bool
    verified_at: int
    verdict: str
    reasons: tuple[str, ...]

    @property
    def digest(self) -> str:
        return canonical_hash({
            "schema": "agentpay-x402-local-authorization-verification/1",
            **asdict(self),
        })


def verify_eip3009_locally(
    rpc: JsonRpcClient,
    requirement: X402Requirement,
    authorization: EIP3009Authorization,
    signature: str,
    *,
    now: int,
    recover_address: Callable[
        [X402Requirement, EIP3009Authorization, str], str
    ] = recover_eip712_address,
) -> LocalAuthorizationVerification:
    signature = validate_signature(signature)
    reasons: list[str] = []

    if authorization.to != requirement.pay_to or authorization.value != requirement.amount:
        reasons.append("authorization-requirement-mismatch")
    if now <= authorization.valid_after:
        reasons.append("authorization-not-yet-valid")
    if now >= authorization.valid_before:
        reasons.append("authorization-expired")

    chain_id = _rpc_int(rpc.call("eth_chainId", []), "x402-local-chain-unavailable")
    if chain_id != requirement.chain_id:
        reasons.append("chain-mismatch")

    code = str(rpc.call("eth_getCode", [requirement.asset, "latest"]) or "").lower()
    if code in {"", "0x", "0x0"}:
        reasons.append("asset-contract-code-missing")

    recovered = recover_address(requirement, authorization, signature).lower()
    if recovered != authorization.from_address.lower():
        reasons.append("signature-payer-mismatch")

    balance_call = "0x" + BALANCE_OF_SELECTOR + _word_address(authorization.from_address)
    balance = _rpc_int(
        rpc.call("eth_call", [{"to": requirement.asset, "data": balance_call}, "latest"]),
        "x402-local-balance-unavailable",
    )
    if balance < authorization.value:
        reasons.append("insufficient-balance")

    auth_call = (
        "0x"
        + AUTHORIZATION_STATE_SELECTOR
        + _word_address(authorization.from_address)
        + _word_bytes32(authorization.nonce)
    )
    authorization_state = _rpc_int(
        rpc.call("eth_call", [{"to": requirement.asset, "data": auth_call}, "latest"]),
        "x402-local-authorization-state-unavailable",
    )
    used = authorization_state != 0
    if used:
        reasons.append("authorization-already-used")

    simulation_ok = False
    if not reasons:
        calldata = encode_transfer_with_authorization_calldata(authorization, signature)
        try:
            rpc.call("eth_call", [{"to": requirement.asset, "data": calldata}, "latest"])
            simulation_ok = True
        except Exception:
            reasons.append("transfer-with-authorization-simulation-failed")

    return LocalAuthorizationVerification(
        payer=authorization.from_address,
        recipient=authorization.to,
        amount=authorization.value,
        asset=requirement.asset,
        network=requirement.network,
        nonce=authorization.nonce,
        balance_atomic=balance,
        authorization_used=used,
        transfer_simulation_ok=simulation_ok,
        verified_at=now,
        verdict="VERIFIED" if not reasons else "NOT VERIFIED",
        reasons=tuple(reasons) or ("local-eip3009-authorization-verified",),
    )


def local_verify_response(
    rpc: JsonRpcClient,
    requirement: X402Requirement,
    authorization: EIP3009Authorization,
    signature: str,
    *,
    now: int,
) -> dict:
    result = verify_eip3009_locally(
        rpc, requirement, authorization, signature, now=now
    )
    return {
        "isValid": result.verdict == "VERIFIED",
        "payer": result.payer,
        "invalidReason": None if result.verdict == "VERIFIED" else ",".join(result.reasons),
        "verificationSource": "local-independent",
        "verificationDigest": result.digest,
        "verification": asdict(result),
    }
