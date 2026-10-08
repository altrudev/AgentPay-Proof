import json
import unittest

from src.x402 import (
    TRANSFER_WITH_AUTHORIZATION_SELECTOR,
    encode_transfer_with_authorization_calldata,
    decode_transfer_with_authorization_calldata,
    EIP3009Authorization,
    X402Error,
    X402Requirement,
    eip712_typed_data,
    new_authorization,
    observe_eip3009_settlement,
    payment_payload,
    select_exact_eip3009_requirement,
    settlement_transaction,
    wallet_sign_request,
    AUTHORIZATION_USED_TOPIC,
)
from src.settlement import TRANSFER_TOPIC, SettlementError

TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
PAYEE = "0x000000000000000000000000000000000000beef"
PAYER = "0x000000000000000000000000000000000000cafe"
RESOURCE = "https://provider.example/v1/render-verify"
NOW = 1_800_000_000
TX = "0x" + "12" * 32


def required(amount="30000", resource=RESOURCE, payee=PAYEE):
    return {
        "x402Version": 2,
        "resource": {"url": resource, "description": "render verify", "mimeType": "application/json"},
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "amount": amount,
                "asset": TOKEN,
                "payTo": payee,
                "maxTimeoutSeconds": 60,
                "extra": {
                    "assetTransferMethod": "eip3009",
                    "paymentFlow": "authorization",
                    "name": "USD Coin",
                    "version": "2",
                },
            }
        ],
    }


def transfer_with_authorization_input(authorization):
    def address_word(value):
        return value[2:].lower().rjust(64, "0")
    def int_word(value):
        return hex(int(value))[2:].rjust(64, "0")
    return TRANSFER_WITH_AUTHORIZATION_SELECTOR + "".join((
        address_word(authorization.from_address),
        address_word(authorization.to),
        int_word(authorization.value),
        int_word(authorization.valid_after),
        int_word(authorization.valid_before),
        authorization.nonce[2:].lower(),
        int_word(27),
        "11" * 32,
        "22" * 32,
    ))


def topic_address(address):
    return "0x" + address[2:].lower().rjust(64, "0")


class FakeRpc:
    def __init__(self, authorization, requirement, *, omit_auth=False, omit_transfer=False, input_override=None):
        self.authorization = authorization
        self.requirement = requirement
        self.omit_auth = omit_auth
        self.omit_transfer = omit_transfer
        self.input_override = input_override

    def call(self, method, params):
        if method == "eth_chainId":
            return hex(8453)
        if method == "eth_getTransactionByHash":
            return {
                "hash": TX, "to": TOKEN,
                "from": "0x0000000000000000000000000000000000001111",
                "input": self.input_override or transfer_with_authorization_input(self.authorization),
            }
        if method == "eth_getTransactionReceipt":
            logs = []
            if not self.omit_auth:
                logs.append({
                    "address": TOKEN,
                    "topics": [AUTHORIZATION_USED_TOPIC, topic_address(PAYER), self.authorization.nonce],
                    "data": "0x",
                })
            if not self.omit_transfer:
                logs.append({
                    "address": TOKEN,
                    "topics": [TRANSFER_TOPIC, topic_address(PAYER), topic_address(PAYEE)],
                    "data": hex(self.requirement.amount),
                })
            return {"status": "0x1", "transactionHash": TX, "logs": logs}
        raise AssertionError(method)


class X402Tests(unittest.TestCase):
    def test_transfer_calldata_encoder_matches_observer_decoder(self):
        req = self.requirement
        auth = self.authorization
        sig = "0x" + "11" * 32 + "22" * 32 + "1b"
        encoded = encode_transfer_with_authorization_calldata(auth, sig)
        decoded = decode_transfer_with_authorization_calldata(encoded)
        self.assertEqual(decoded["from"], auth.from_address)
        self.assertEqual(decoded["to"], auth.to)
        self.assertEqual(decoded["value"], auth.value)
        self.assertEqual(decoded["validAfter"], auth.valid_after)
        self.assertEqual(decoded["validBefore"], auth.valid_before)
        self.assertEqual(decoded["nonce"], auth.nonce)
        self.assertEqual(decoded["v"], 27)
        self.assertEqual(decoded["r"], "0x" + "11" * 32)
        self.assertEqual(decoded["s"], "0x" + "22" * 32)

    def setUp(self):
        self.requirement = select_exact_eip3009_requirement(
            required(), resource_url=RESOURCE, chain_id=8453, asset=TOKEN, pay_to=PAYEE, amount=30000
        )
        self.authorization = new_authorization(
            self.requirement, payer=PAYER, now=NOW, authority_expires_at=NOW + 120,
            nonce="0x" + "ab" * 32,
        )

    def test_select_exact_requirement_binds_resource_network_token_payee_and_amount(self):
        self.assertEqual(self.requirement.network, "eip155:8453")
        self.assertEqual(self.requirement.amount, 30000)
        self.assertEqual(self.requirement.asset_transfer_method, "eip3009")
        self.assertEqual(self.requirement.payment_flow, "authorization")

    def test_wrong_resource_or_amount_cannot_be_selected(self):
        with self.assertRaisesRegex(X402Error, "x402-resource-binding-mismatch"):
            select_exact_eip3009_requirement(required(), resource_url="https://other.example", chain_id=8453, asset=TOKEN, pay_to=PAYEE, amount=30000)
        with self.assertRaisesRegex(X402Error, "x402-exact-requirement-not-unique"):
            select_exact_eip3009_requirement(required(), resource_url=RESOURCE, chain_id=8453, asset=TOKEN, pay_to=PAYEE, amount=1)

    def test_base_usdc_domain_substitution_is_rejected(self):
        tampered = required()
        tampered["accepts"][0]["extra"]["name"] = "Fake USD Coin"
        with self.assertRaisesRegex(X402Error, "x402-usdc-domain-mismatch"):
            select_exact_eip3009_requirement(
                tampered, resource_url=RESOURCE, chain_id=8453, asset=TOKEN, pay_to=PAYEE, amount=30000
            )

    def test_typed_data_is_exact_eip3009_domain(self):
        typed = eip712_typed_data(self.requirement, self.authorization)
        self.assertEqual(typed["primaryType"], "TransferWithAuthorization")
        self.assertEqual(typed["domain"]["chainId"], 8453)
        self.assertEqual(typed["domain"]["verifyingContract"], TOKEN)
        self.assertEqual(typed["message"]["to"], PAYEE)
        self.assertEqual(typed["message"]["nonce"], "0x" + "ab" * 32)

    def test_wallet_request_only_requests_typed_signature_not_transaction(self):
        request = wallet_sign_request(self.requirement, self.authorization)
        self.assertEqual(request["method"], "eth_signTypedData_v4")
        self.assertEqual(request["params"][0], PAYER)
        typed = json.loads(request["params"][1])
        self.assertEqual(typed["message"]["value"], "30000")

    def test_payment_payload_binds_authorization(self):
        signature = "0x" + "11" * 65
        payload = payment_payload(self.requirement, self.authorization, signature)
        self.assertEqual(payload["x402Version"], 2)
        self.assertEqual(payload["payload"]["authorization"]["nonce"], self.authorization.nonce)
        self.assertEqual(payload["accepted"]["amount"], "30000")

    def test_settlement_response_must_match_network_and_payer(self):
        tx = settlement_transaction({"success": True, "transaction": TX, "network": "eip155:8453", "payer": PAYER}, payer=PAYER, network="eip155:8453")
        self.assertEqual(tx, TX)
        with self.assertRaisesRegex(X402Error, "x402-settlement-network-mismatch"):
            settlement_transaction({"success": True, "transaction": TX, "network": "eip155:1", "payer": PAYER}, payer=PAYER, network="eip155:8453")

    def test_observer_requires_nonce_consumption_and_exact_transfer(self):
        settlement = observe_eip3009_settlement(FakeRpc(self.authorization, self.requirement), TX, self.requirement, self.authorization)
        self.assertEqual(settlement.sender, PAYER)
        self.assertEqual(settlement.recipient, PAYEE)
        self.assertEqual(settlement.amount_atomic, 30000)
        with self.assertRaisesRegex(SettlementError, "x402-authorization-used-log-not-found"):
            observe_eip3009_settlement(FakeRpc(self.authorization, self.requirement, omit_auth=True), TX, self.requirement, self.authorization)
        with self.assertRaisesRegex(SettlementError, "x402-matching-transfer-log-not-found"):
            observe_eip3009_settlement(FakeRpc(self.authorization, self.requirement, omit_transfer=True), TX, self.requirement, self.authorization)

    def test_payment_payload_preserves_resource_metadata_and_extensions(self):
        signature = "0x" + "11" * 65
        resource = {
            "url": RESOURCE,
            "description": "render verify",
            "mimeType": "application/json",
            "serviceName": "Bounded Verify",
        }
        extensions = {
            "com.example.policy": {
                "info": {"purpose": "release-validation"},
                "schema": {"type": "object"},
            }
        }
        payload = payment_payload(
            self.requirement, self.authorization, signature,
            resource=resource, extensions=extensions,
        )
        self.assertEqual(payload["resource"], resource)
        self.assertEqual(payload["extensions"], extensions)

    def test_unknown_requirement_semantics_fail_closed(self):
        tampered = required()
        tampered["accepts"][0]["extra"]["futureSettlementMode"] = "magic"
        with self.assertRaisesRegex(X402Error, "x402-exact-requirement-not-unique"):
            select_exact_eip3009_requirement(
                tampered, resource_url=RESOURCE, chain_id=8453,
                asset=TOKEN, pay_to=PAYEE, amount=30000,
            )

    def test_observer_binds_full_authorization_calldata(self):
        altered = EIP3009Authorization(
            from_address=self.authorization.from_address,
            to=self.authorization.to,
            value=self.authorization.value,
            valid_after=self.authorization.valid_after,
            valid_before=self.authorization.valid_before + 1,
            nonce=self.authorization.nonce,
        )
        with self.assertRaisesRegex(SettlementError, "x402-authorization-calldata-mismatch"):
            observe_eip3009_settlement(
                FakeRpc(
                    self.authorization, self.requirement,
                    input_override=transfer_with_authorization_input(altered),
                ),
                TX, self.requirement, self.authorization,
            )


if __name__ == "__main__":
    unittest.main()
