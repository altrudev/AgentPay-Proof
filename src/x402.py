from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import secrets
from typing import Any, Protocol

from src.model import Settlement, canonical_hash
from src.settlement import JsonRpcClient, SettlementError, TRANSFER_TOPIC

X402_VERSION = 2
X402_SCHEME = "exact"
X402_EIP3009 = "eip3009"
X402_AUTHORIZATION_FLOW = "authorization"
BASE_MAINNET_CHAIN_ID = 8453
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
BASE_USDC_EIP712_NAME = "USD Coin"
BASE_USDC_EIP712_VERSION = "2"
AUTHORIZATION_USED_TOPIC = "0x98de503528ee59b575ef0c0a2576a82497bfc029a5685b209e9ec333479b10a5"


class X402Error(ValueError):
    pass


def _address(value: str) -> str:
    value = str(value).strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise X402Error("x402-address-invalid")
    int(value[2:], 16)
    return value


def _bytes32(value: str) -> str:
    value = str(value).strip().lower()
    if not value.startswith("0x") or len(value) != 66:
        raise X402Error("x402-bytes32-invalid")
    int(value[2:], 16)
    return value


def _topic_address(topic: str) -> str:
    topic = _bytes32(topic)
    return _address("0x" + topic[-40:])


def _hex_int(value: str | int) -> int:
    return value if isinstance(value, int) else int(value, 16)


@dataclass(frozen=True)
class X402Requirement:
    resource_url: str
    scheme: str
    network: str
    amount: int
    asset: str
    pay_to: str
    max_timeout_seconds: int
    token_name: str
    token_version: str
    asset_transfer_method: str = X402_EIP3009
    payment_flow: str = X402_AUTHORIZATION_FLOW

    def __post_init__(self) -> None:
        if not str(self.resource_url).startswith("https://"):
            raise X402Error("x402-resource-url-not-https")
        if self.scheme != X402_SCHEME:
            raise X402Error("x402-scheme-unsupported")
        if not str(self.network).startswith("eip155:"):
            raise X402Error("x402-network-invalid")
        if self.amount <= 0:
            raise X402Error("x402-amount-invalid")
        object.__setattr__(self, "asset", _address(self.asset))
        object.__setattr__(self, "pay_to", _address(self.pay_to))
        if self.max_timeout_seconds <= 0 or self.max_timeout_seconds > 300:
            raise X402Error("x402-timeout-outside-policy")
        if not str(self.token_name).strip() or not str(self.token_version).strip():
            raise X402Error("x402-token-domain-incomplete")
        if self.asset_transfer_method != X402_EIP3009:
            raise X402Error("x402-transfer-method-unsupported")
        if self.payment_flow != X402_AUTHORIZATION_FLOW:
            raise X402Error("x402-payment-flow-unsupported")

    @property
    def chain_id(self) -> int:
        try:
            return int(self.network.split(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise X402Error("x402-network-invalid") from exc

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": "agentpay-x402-requirement/1", **asdict(self)})

    def wire(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "network": self.network,
            "amount": str(self.amount),
            "asset": self.asset,
            "payTo": self.pay_to,
            "maxTimeoutSeconds": self.max_timeout_seconds,
            "extra": {
                "assetTransferMethod": self.asset_transfer_method,
                "paymentFlow": self.payment_flow,
                "name": self.token_name,
                "version": self.token_version,
            },
        }


@dataclass(frozen=True)
class EIP3009Authorization:
    from_address: str
    to: str
    value: int
    valid_after: int
    valid_before: int
    nonce: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_address", _address(self.from_address))
        object.__setattr__(self, "to", _address(self.to))
        object.__setattr__(self, "nonce", _bytes32(self.nonce))
        if self.value <= 0:
            raise X402Error("x402-authorization-value-invalid")
        if self.valid_after < 0 or self.valid_before <= self.valid_after:
            raise X402Error("x402-authorization-window-invalid")

    @property
    def digest(self) -> str:
        return canonical_hash({"schema": "agentpay-eip3009-authorization/1", **asdict(self)})

    def wire(self) -> dict[str, str]:
        return {
            "from": self.from_address,
            "to": self.to,
            "value": str(self.value),
            "validAfter": str(self.valid_after),
            "validBefore": str(self.valid_before),
            "nonce": self.nonce,
        }


def select_exact_eip3009_requirement(
    payment_required: dict[str, Any],
    *,
    resource_url: str,
    chain_id: int,
    asset: str,
    pay_to: str,
    amount: int,
) -> X402Requirement:
    if not isinstance(payment_required, dict) or payment_required.get("x402Version") != X402_VERSION:
        raise X402Error("x402-version-invalid")
    resource = payment_required.get("resource")
    if not isinstance(resource, dict) or resource.get("url") != resource_url:
        raise X402Error("x402-resource-binding-mismatch")
    accepts = payment_required.get("accepts")
    if not isinstance(accepts, list) or not accepts:
        raise X402Error("x402-accepts-missing")

    expected_asset = _address(asset)
    expected_payee = _address(pay_to)
    expected_network = f"eip155:{chain_id}"
    candidates: list[X402Requirement] = []
    for item in accepts:
        if not isinstance(item, dict):
            continue
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        method = extra.get("assetTransferMethod", X402_EIP3009)
        flow = extra.get("paymentFlow", X402_AUTHORIZATION_FLOW)
        try:
            candidate = X402Requirement(
                resource_url=resource_url,
                scheme=str(item.get("scheme", "")),
                network=str(item.get("network", "")),
                amount=int(str(item.get("amount", "0"))),
                asset=str(item.get("asset", "")),
                pay_to=str(item.get("payTo", "")),
                max_timeout_seconds=int(item.get("maxTimeoutSeconds", 0)),
                token_name=str(extra.get("name", "")),
                token_version=str(extra.get("version", "")),
                asset_transfer_method=str(method),
                payment_flow=str(flow),
            )
        except (ValueError, X402Error):
            continue
        if (
            candidate.network == expected_network
            and candidate.asset == expected_asset
            and candidate.pay_to == expected_payee
            and candidate.amount == amount
        ):
            candidates.append(candidate)
    if len(candidates) != 1:
        raise X402Error("x402-exact-requirement-not-unique")
    selected = candidates[0]
    if selected.chain_id == BASE_MAINNET_CHAIN_ID and selected.asset == BASE_USDC:
        if selected.token_name != BASE_USDC_EIP712_NAME or selected.token_version != BASE_USDC_EIP712_VERSION:
            raise X402Error("x402-usdc-domain-mismatch")
    return selected


def new_authorization(
    requirement: X402Requirement,
    *,
    payer: str,
    now: int,
    authority_expires_at: int,
    nonce: str | None = None,
) -> EIP3009Authorization:
    valid_after = max(0, now - 1)
    valid_before = min(now + requirement.max_timeout_seconds, authority_expires_at)
    if valid_before <= now + 2:
        raise X402Error("x402-authorization-window-too-short")
    return EIP3009Authorization(
        from_address=payer,
        to=requirement.pay_to,
        value=requirement.amount,
        valid_after=valid_after,
        valid_before=valid_before,
        nonce=nonce or ("0x" + secrets.token_hex(32)),
    )


def eip712_typed_data(
    requirement: X402Requirement,
    authorization: EIP3009Authorization,
) -> dict[str, Any]:
    if authorization.to != requirement.pay_to or authorization.value != requirement.amount:
        raise X402Error("x402-authorization-requirement-mismatch")
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "domain": {
            "name": requirement.token_name,
            "version": requirement.token_version,
            "chainId": requirement.chain_id,
            "verifyingContract": requirement.asset,
        },
        "primaryType": "TransferWithAuthorization",
        "message": authorization.wire(),
    }


def wallet_sign_request(requirement: X402Requirement, authorization: EIP3009Authorization) -> dict[str, Any]:
    typed = eip712_typed_data(requirement, authorization)
    return {
        "method": "eth_signTypedData_v4",
        "params": [authorization.from_address, json.dumps(typed, sort_keys=True, separators=(",", ":"))],
    }


def validate_signature(signature: str) -> str:
    signature = str(signature).strip().lower()
    if not signature.startswith("0x") or len(signature) != 132:
        raise X402Error("x402-signature-invalid")
    int(signature[2:], 16)
    return signature


def payment_payload(
    requirement: X402Requirement,
    authorization: EIP3009Authorization,
    signature: str,
) -> dict[str, Any]:
    signature = validate_signature(signature)
    return {
        "x402Version": X402_VERSION,
        "resource": {"url": requirement.resource_url},
        "accepted": requirement.wire(),
        "payload": {
            "signature": signature,
            "authorization": authorization.wire(),
        },
        "extensions": {},
    }


class X402Facilitator(Protocol):
    def verify(self, payment_payload: dict[str, Any], requirement: dict[str, Any]) -> dict[str, Any]: ...
    def settle(self, payment_payload: dict[str, Any], requirement: dict[str, Any]) -> dict[str, Any]: ...


def assert_verify_response(response: dict[str, Any], *, payer: str) -> None:
    if not isinstance(response, dict) or response.get("isValid") is not True:
        reason = response.get("invalidReason", "invalid") if isinstance(response, dict) else "invalid"
        raise X402Error(f"x402-facilitator-verification-failed:{reason}")
    if response.get("payer") and _address(response["payer"]) != _address(payer):
        raise X402Error("x402-facilitator-payer-mismatch")


def settlement_transaction(response: dict[str, Any], *, payer: str, network: str) -> str:
    if not isinstance(response, dict):
        raise X402Error("x402-settlement-response-invalid")
    if response.get("success") is not True:
        reason = str(response.get("errorReason", "settlement-failed"))
        tx = str(response.get("transaction", ""))
        if reason == "settlement_pending" and tx.startswith("0x") and len(tx) >= 10:
            raise X402Error(f"x402-settlement-pending:{tx}")
        raise X402Error(f"x402-settlement-failed:{reason}")
    if response.get("network") != network:
        raise X402Error("x402-settlement-network-mismatch")
    if response.get("payer") and _address(response["payer"]) != _address(payer):
        raise X402Error("x402-settlement-payer-mismatch")
    tx = str(response.get("transaction", ""))
    if not tx.startswith("0x") or len(tx) < 10:
        raise X402Error("x402-settlement-transaction-invalid")
    return tx


def observe_eip3009_settlement(
    rpc: JsonRpcClient,
    tx_hash: str,
    requirement: X402Requirement,
    authorization: EIP3009Authorization,
) -> Settlement:
    chain = rpc.call("eth_chainId", [])
    if chain is None or _hex_int(chain) != requirement.chain_id:
        raise SettlementError("x402-rpc-network-mismatch")
    tx = rpc.call("eth_getTransactionByHash", [tx_hash])
    receipt = rpc.call("eth_getTransactionReceipt", [tx_hash])
    if not tx or not receipt:
        raise SettlementError("x402-transaction-not-found")
    if receipt.get("status") not in ("0x1", 1):
        raise SettlementError("x402-transaction-not-successful")
    if _address(tx.get("to", "")) != requirement.asset:
        raise SettlementError("x402-token-contract-mismatch")

    auth_used = False
    transfer_seen = False
    for log in receipt.get("logs", []):
        try:
            if _address(log.get("address", "")) != requirement.asset:
                continue
        except X402Error:
            continue
        topics = log.get("topics", [])
        if len(topics) >= 3 and str(topics[0]).lower() == AUTHORIZATION_USED_TOPIC:
            if _topic_address(topics[1]) == authorization.from_address and _bytes32(topics[2]) == authorization.nonce:
                auth_used = True
        if len(topics) >= 3 and str(topics[0]).lower() == TRANSFER_TOPIC:
            if (
                _topic_address(topics[1]) == authorization.from_address
                and _topic_address(topics[2]) == requirement.pay_to
                and _hex_int(log.get("data", "0x0")) == requirement.amount
            ):
                transfer_seen = True
    if not auth_used:
        raise SettlementError("x402-authorization-used-log-not-found")
    if not transfer_seen:
        raise SettlementError("x402-matching-transfer-log-not-found")

    observed_hash = receipt.get("transactionHash") or tx.get("hash")
    if str(observed_hash).lower() != str(tx_hash).lower():
        raise SettlementError("x402-transaction-hash-mismatch")
    return Settlement(
        chain_id=requirement.chain_id,
        transaction_hash=tx_hash,
        sender=authorization.from_address,
        recipient=requirement.pay_to,
        asset_contract=requirement.asset,
        amount_atomic=requirement.amount,
        status="FINALIZED",
    )
