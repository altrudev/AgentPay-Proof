import os
import tempfile
import unittest

from src.execution import (
    ExecutionJournal, ExecutionStateError, GovernedOnChainSettlementProvider,
    SettlementInDoubt,
)
from src.model import Intent, Quote, Settlement, decide
from src.settlement import SettlementError, transaction_request

TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
RECIPIENT = "0x000000000000000000000000000000000000beef"
SENDER = "0x000000000000000000000000000000000000cafe"
NOW = 1_800_000_000


def fixture():
    intent = Intent("i", "agent", "svc", "req", NOW)
    quote = Quote("q", "svc", RECIPIENT, 8453, TOKEN, 250_000, NOW + 300, "req")
    authority = decide(
        intent, quote, decision_id="d", maximum_amount_atomic=1_000_000,
        recipient=RECIPIENT, service_id="svc", chain_id=8453,
        asset_contract=TOKEN, expires_at=NOW + 300, now=NOW,
    )
    return quote, authority


class FakeRpc:
    def __init__(self, fail=False):
        self.fail = fail

    def observe(self, tx_hash, quote, expected_sender):
        if self.fail:
            raise SettlementError("transaction-not-found")
        return Settlement(
            quote.chain_id, tx_hash, expected_sender, quote.recipient,
            quote.asset_contract, quote.amount_atomic, "FINALIZED",
        )


class ExecutionJournalTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.journal = ExecutionJournal(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_duplicate_authority_cannot_be_reserved(self):
        quote, authority = fixture()
        self.journal.reserve(authority, quote)
        with self.assertRaisesRegex(ExecutionStateError, "authority-already-reserved"):
            self.journal.reserve(authority, quote)

    def test_happy_path_consumes_authority_once(self):
        quote, authority = fixture()
        provider = GovernedOnChainSettlementProvider(
            self.journal, lambda tx: "0xabc", FakeRpc(), SENDER
        )
        settlement = provider.settle(
            transaction_request(authority, quote, now=NOW), quote, authority
        )
        self.assertEqual(settlement.transaction_hash, "0xabc")
        self.assertEqual(self.journal.get(authority.decision_id).state, "CONSUMED")
        with self.assertRaisesRegex(ExecutionStateError, "authority-already-reserved"):
            provider.settle(transaction_request(authority, quote, now=NOW), quote, authority)

    def test_ambiguous_broadcast_never_retries_automatically(self):
        quote, authority = fixture()

        def fail(_tx):
            raise TimeoutError("wallet timed out")

        provider = GovernedOnChainSettlementProvider(self.journal, fail, FakeRpc(), SENDER)
        with self.assertRaisesRegex(SettlementInDoubt, "broadcast-outcome-unknown"):
            provider.settle(transaction_request(authority, quote, now=NOW), quote, authority)
        self.assertEqual(self.journal.get(authority.decision_id).state, "IN_DOUBT")

    def test_rpc_uncertainty_preserves_tx_hash_and_in_doubt(self):
        quote, authority = fixture()
        provider = GovernedOnChainSettlementProvider(
            self.journal, lambda tx: "0xabc", FakeRpc(fail=True), SENDER
        )
        with self.assertRaisesRegex(SettlementInDoubt, "settlement-not-yet-reconciled"):
            provider.settle(transaction_request(authority, quote, now=NOW), quote, authority)
        record = self.journal.get(authority.decision_id)
        self.assertEqual(record.state, "IN_DOUBT")
        self.assertEqual(record.transaction_hash, "0xabc")

    def test_transaction_mutation_is_rejected_before_reservation(self):
        quote, authority = fixture()
        tx = transaction_request(authority, quote, now=NOW)
        tx["value"] = 1
        provider = GovernedOnChainSettlementProvider(
            self.journal, lambda tx: "0xabc", FakeRpc(), SENDER
        )
        with self.assertRaisesRegex(ExecutionStateError, "transaction-request-mismatch"):
            provider.settle(tx, quote, authority)
        with self.assertRaisesRegex(ExecutionStateError, "execution-not-found"):
            self.journal.get(authority.decision_id)


if __name__ == "__main__":
    unittest.main()
