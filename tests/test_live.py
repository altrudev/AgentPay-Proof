import os
import tempfile
import unittest
from unittest.mock import patch

from src.live import LiveConfig, LiveCoordinator, LivePaymentError
from src.model import Settlement
from src.settlement import SettlementError

TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
RECIPIENT = "0x000000000000000000000000000000000000beef"
SENDER = "0x000000000000000000000000000000000000cafe"
NOW = 1_800_000_000


class FakeRpc:
    def __init__(self, fail=False):
        self.fail = fail

    def observe(self, tx_hash, quote, sender):
        if self.fail:
            raise SettlementError("transaction-not-found")
        return Settlement(
            quote.chain_id, tx_hash, sender, quote.recipient,
            quote.asset_contract, quote.amount_atomic, "FINALIZED",
        )


class LiveCoordinatorTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.config = LiveConfig(
            rpc_url="https://rpc.example",
            journal_path=self.path,
            chain_id=8453,
            asset_contract=TOKEN,
            recipient=RECIPIENT,
            maximum_amount_atomic=1_000_000,
        )

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def coordinator(self, fail=False):
        c = LiveCoordinator(self.config)
        c.rpc = FakeRpc(fail=fail)
        return c

    def test_prepare_reserves_before_wallet_handoff(self):
        c = self.coordinator()
        out = c.prepare("One. Two.", amount_atomic=250_000, agent_id="agent:web", now=NOW)
        self.assertEqual(out["status"], "AWAITING_WALLET")
        self.assertEqual(c.journal.get(out["decision_id"]).state, "PREPARED")
        self.assertEqual(out["wallet_request"]["chainId"], hex(8453))
        self.assertEqual(out["wallet_request"]["to"], TOKEN)

    def test_over_limit_denies_without_reservation(self):
        c = self.coordinator()
        out = c.prepare("One.", amount_atomic=2_000_000, agent_id="agent:web", now=NOW)
        self.assertEqual(out["status"], "DENIED")
        self.assertIsNone(out["wallet_request"])

    def test_explicit_wallet_rejection_can_abort_prepared(self):
        c = self.coordinator()
        out = c.prepare("One.", amount_atomic=250_000, agent_id="agent:web", now=NOW)
        closed = c.abort(out["decision_id"])
        self.assertEqual(closed["state"], "ABORTED")

    def test_reconcile_observes_chain_then_consumes(self):
        c = self.coordinator()
        out = c.prepare("One. Two. Three.", amount_atomic=250_000, agent_id="agent:web", now=NOW)
        result = c.reconcile(out["decision_id"], "0xabc1234567", SENDER, now=NOW + 1)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["verification"], {"verdict": "VERIFIED", "errors": []})
        self.assertEqual(c.journal.get(out["decision_id"]).state, "CONSUMED")

    def test_rpc_uncertainty_becomes_in_doubt(self):
        c = self.coordinator(fail=True)
        out = c.prepare("One.", amount_atomic=250_000, agent_id="agent:web", now=NOW)
        with self.assertRaisesRegex(LivePaymentError, "settlement-not-observed"):
            c.reconcile(out["decision_id"], "0xabc1234567", SENDER, now=NOW + 1)
        record = c.journal.get(out["decision_id"])
        self.assertEqual(record.state, "IN_DOUBT")
        self.assertEqual(record.transaction_hash, "0xabc1234567")

    def test_consumed_authority_cannot_reconcile_again(self):
        c = self.coordinator()
        out = c.prepare("One.", amount_atomic=250_000, agent_id="agent:web", now=NOW)
        c.reconcile(out["decision_id"], "0xabc1234567", SENDER, now=NOW + 1)
        with self.assertRaisesRegex(LivePaymentError, "reconciliation-not-allowed:CONSUMED"):
            c.reconcile(out["decision_id"], "0xabc1234567", SENDER, now=NOW + 2)


if __name__ == "__main__":
    unittest.main()
