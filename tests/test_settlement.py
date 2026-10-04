import unittest

from src.model import Intent, Quote, decide
from src.settlement import (
    TRANSFER_TOPIC, SettlementError, erc20_transfer_calldata,
    settlement_from_rpc, transaction_request,
)

TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
RECIPIENT = "0x000000000000000000000000000000000000beef"
SENDER = "0x000000000000000000000000000000000000cafe"
NOW = 1_800_000_000


def topic(address):
    return "0x" + address[2:].lower().rjust(64, "0")


def fixture(amount=250_000):
    intent = Intent("i", "agent", "svc", "req", NOW)
    quote = Quote("q", "svc", RECIPIENT, 8453, TOKEN, amount, NOW + 300, "req")
    authority = decide(
        intent, quote, decision_id="d", maximum_amount_atomic=1_000_000,
        recipient=RECIPIENT, service_id="svc", chain_id=8453,
        asset_contract=TOKEN, expires_at=NOW + 300, now=NOW,
    )
    return quote, authority


class SettlementAdapterTests(unittest.TestCase):
    def test_transaction_request_is_exact_erc20_transfer(self):
        quote, authority = fixture()
        req = transaction_request(authority, quote, now=NOW)
        self.assertEqual(req["to"], TOKEN)
        self.assertEqual(req["value"], 0)
        self.assertEqual(req["data"], erc20_transfer_calldata(RECIPIENT, 250_000))

    def test_denied_authority_cannot_construct_transaction(self):
        quote, authority = fixture(2_000_000)
        self.assertEqual(authority.decision, "DENY")
        with self.assertRaisesRegex(SettlementError, "settlement-requires-permit"):
            transaction_request(authority, quote, now=NOW)

    def test_rpc_receipt_requires_matching_transfer_log(self):
        quote, _ = fixture()
        tx = {"hash": "0xabc", "from": SENDER, "to": TOKEN, "chainId": "0x2105"}
        receipt = {
            "status": "0x1", "transactionHash": "0xabc",
            "logs": [{
                "address": TOKEN,
                "topics": [TRANSFER_TOPIC, topic(SENDER), topic(RECIPIENT)],
                "data": hex(250_000),
            }],
        }
        settlement = settlement_from_rpc(tx=tx, receipt=receipt, quote=quote, expected_sender=SENDER)
        self.assertEqual(settlement.amount_atomic, 250_000)
        self.assertEqual(settlement.status, "FINALIZED")

    def test_fabricated_hash_without_transfer_is_rejected(self):
        quote, _ = fixture()
        tx = {"hash": "0xabc", "from": SENDER, "to": TOKEN, "chainId": "0x2105"}
        receipt = {"status": "0x1", "transactionHash": "0xabc", "logs": []}
        with self.assertRaisesRegex(SettlementError, "matching-transfer-log-not-found"):
            settlement_from_rpc(tx=tx, receipt=receipt, quote=quote, expected_sender=SENDER)

    def test_wrong_recipient_log_is_rejected(self):
        quote, _ = fixture()
        wrong = "0x000000000000000000000000000000000000dead"
        tx = {"hash": "0xabc", "from": SENDER, "to": TOKEN, "chainId": "0x2105"}
        receipt = {
            "status": "0x1", "transactionHash": "0xabc",
            "logs": [{"address": TOKEN, "topics": [TRANSFER_TOPIC, topic(SENDER), topic(wrong)], "data": hex(250_000)}],
        }
        with self.assertRaisesRegex(SettlementError, "matching-transfer-log-not-found"):
            settlement_from_rpc(tx=tx, receipt=receipt, quote=quote, expected_sender=SENDER)

    def test_wrong_amount_log_is_rejected(self):
        quote, _ = fixture()
        tx = {"hash": "0xabc", "from": SENDER, "to": TOKEN, "chainId": "0x2105"}
        receipt = {
            "status": "0x1", "transactionHash": "0xabc",
            "logs": [{"address": TOKEN, "topics": [TRANSFER_TOPIC, topic(SENDER), topic(RECIPIENT)], "data": hex(1)}],
        }
        with self.assertRaisesRegex(SettlementError, "matching-transfer-log-not-found"):
            settlement_from_rpc(tx=tx, receipt=receipt, quote=quote, expected_sender=SENDER)


if __name__ == "__main__":
    unittest.main()
