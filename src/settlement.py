from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.model import Authority, Quote, Settlement

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class SettlementError(ValueError):
    pass


def _norm_address(value: str) -> str:
    value = value.lower()
    if not value.startswith("0x") or len(value) != 42:
        raise SettlementError("invalid-address")
    int(value[2:], 16)
    return value


def _topic_address(topic: str) -> str:
    if not isinstance(topic, str) or not topic.startswith("0x") or len(topic) != 66:
        raise SettlementError("invalid-address-topic")
    return _norm_address("0x" + topic[-40:])


def _hex_int(value: str | int) -> int:
    return value if isinstance(value, int) else int(value, 16)


def assert_authorized_quote(authority: Authority, quote: Quote, *, now: int) -> None:
    if authority.decision != "PERMIT":
        raise SettlementError("settlement-requires-permit")
    if authority.quote_id != quote.quote_id:
        raise SettlementError("quote-binding-mismatch")
    if authority.recipient.lower() != quote.recipient.lower():
        raise SettlementError("recipient-binding-mismatch")
    if authority.service_id != quote.service_id:
        raise SettlementError("service-binding-mismatch")
    if authority.chain_id != quote.chain_id:
        raise SettlementError("chain-binding-mismatch")
    if authority.asset_contract.lower() != quote.asset_contract.lower():
        raise SettlementError("asset-binding-mismatch")
    if quote.amount_atomic > authority.maximum_amount_atomic:
        raise SettlementError("amount-exceeds-authority")
    if now > authority.expires_at or now > quote.expires_at:
        raise SettlementError("authority-expired")


def erc20_transfer_calldata(recipient: str, amount_atomic: int) -> str:
    recipient = _norm_address(recipient)
    if amount_atomic <= 0:
        raise SettlementError("amount-invalid")
    # transfer(address,uint256) selector.
    return "0xa9059cbb" + recipient[2:].rjust(64, "0") + hex(amount_atomic)[2:].rjust(64, "0")


def transaction_request(authority: Authority, quote: Quote, *, now: int) -> dict[str, Any]:
    assert_authorized_quote(authority, quote, now=now)
    return {
        "chain_id": quote.chain_id,
        "to": _norm_address(quote.asset_contract),
        "value": 0,
        "data": erc20_transfer_calldata(quote.recipient, quote.amount_atomic),
        "authorization": authority.digest,
        "quote": quote.digest,
    }


def settlement_from_rpc(*, tx: dict[str, Any], receipt: dict[str, Any], quote: Quote,
                        expected_sender: str) -> Settlement:
    if receipt.get("status") not in ("0x1", 1):
        raise SettlementError("transaction-not-successful")
    if _hex_int(tx.get("chainId", quote.chain_id)) != quote.chain_id:
        raise SettlementError("rpc-chain-mismatch")
    if _norm_address(tx["from"]) != _norm_address(expected_sender):
        raise SettlementError("sender-mismatch")
    if _norm_address(tx["to"]) != _norm_address(quote.asset_contract):
        raise SettlementError("token-contract-mismatch")

    matching = []
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        if (_norm_address(log.get("address", "0x" + "0" * 40)) == _norm_address(quote.asset_contract)
                and len(topics) >= 3 and topics[0].lower() == TRANSFER_TOPIC
                and _topic_address(topics[1]) == _norm_address(expected_sender)
                and _topic_address(topics[2]) == _norm_address(quote.recipient)):
            matching.append(_hex_int(log["data"]))
    if quote.amount_atomic not in matching:
        raise SettlementError("matching-transfer-log-not-found")

    tx_hash = receipt.get("transactionHash") or tx.get("hash")
    if not tx_hash:
        raise SettlementError("transaction-hash-missing")
    return Settlement(
        chain_id=quote.chain_id,
        transaction_hash=tx_hash,
        sender=_norm_address(expected_sender),
        recipient=_norm_address(quote.recipient),
        asset_contract=_norm_address(quote.asset_contract),
        amount_atomic=quote.amount_atomic,
        status="FINALIZED",
    )


@dataclass
class JsonRpcClient:
    endpoint: str
    timeout_seconds: int = 10

    def call(self, method: str, params: list[Any]) -> Any:
        # Stdlib only; secrets never enter request bodies.
        import json
        from urllib.request import Request, urlopen
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = Request(self.endpoint, data=payload, headers={"content-type": "application/json"})
        with urlopen(req, timeout=self.timeout_seconds) as response:
            body = json.load(response)
        if "error" in body:
            raise SettlementError(f"rpc-error:{body['error'].get('code', 'unknown')}")
        return body.get("result")

    def observe(self, tx_hash: str, quote: Quote, expected_sender: str) -> Settlement:
        tx = self.call("eth_getTransactionByHash", [tx_hash])
        receipt = self.call("eth_getTransactionReceipt", [tx_hash])
        if not tx or not receipt:
            raise SettlementError("transaction-not-found")
        return settlement_from_rpc(tx=tx, receipt=receipt, quote=quote, expected_sender=expected_sender)
