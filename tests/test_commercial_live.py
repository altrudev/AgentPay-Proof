import os
import tempfile
import unittest

from src.commercial_demo import release_validation_objects
from src.commercial_execution import CommercialCoordinator, CommercialExecutionJournal
from src.commercial_live import CommercialLiveError, PaidCommercialCoordinator
from src.execution import ExecutionJournal
from src.live import LiveConfig
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
            chain_id=quote.chain_id,
            transaction_hash=tx_hash,
            sender=sender,
            recipient=quote.recipient,
            asset_contract=quote.asset_contract,
            amount_atomic=quote.amount_atomic,
            status="FINALIZED",
        )


class PaidCommercialCoordinatorTests(unittest.TestCase):
    def setUp(self):
        fd, self.commercial_path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.commercial_path)
        fd, self.payment_path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.payment_path)

        self.commercial_journal = CommercialExecutionJournal(self.commercial_path)
        self.payment_journal = ExecutionJournal(self.payment_path)
        self.commercial = CommercialCoordinator(self.commercial_journal)
        self.config = LiveConfig(
            rpc_url="https://rpc.example",
            journal_path=self.payment_path,
            chain_id=8453,
            asset_contract=TOKEN,
            recipient=RECIPIENT,
            maximum_amount_atomic=1_000_000,
        )
        self.paid = PaidCommercialCoordinator(
            commercial_journal=self.commercial_journal,
            payment_journal=self.payment_journal,
            live_config=self.config,
            rpc=FakeRpc(),
        )
        self.capsule, self.offers = release_validation_objects(now=NOW)
        self.prepared = self.commercial.prepare(self.capsule, self.offers, now=NOW)
        self.payload = {
            "rendered_page_digest": "rendered:test",
            "reference_digest": "reference:approved-v6",
        }

    def tearDown(self):
        for path in (self.commercial_path, self.payment_path):
            if os.path.exists(path):
                os.unlink(path)

    @property
    def grant_id(self):
        return self.prepared["grant"]["grant_id"]

    @property
    def approval(self):
        return self.prepared["approval_digest"]

    def test_wallet_prepare_binds_exact_commercial_grant_and_route(self):
        out = self.paid.prepare_wallet(
            self.grant_id,
            commercial_approval_digest=self.approval,
            payload=self.payload,
            now=NOW + 1,
        )
        self.assertEqual(out["status"], "AWAITING_WALLET")
        self.assertEqual(out["grant_id"], self.grant_id)
        self.assertEqual(out["route"]["provider_id"], "provider:render-only")
        self.assertEqual(out["route"]["payment_amount_atomic"], 30_000)
        self.assertEqual(out["wallet_request"]["chainId"], hex(8453))
        self.assertEqual(out["wallet_request"]["to"], TOKEN)
        self.assertEqual(out["quote"]["recipient"], RECIPIENT)
        self.assertEqual(out["quote"]["amount_atomic"], 30_000)
        self.assertEqual(self.commercial_journal.get(self.grant_id).state, "APPROVED")
        self.assertEqual(
            self.payment_journal.get(out["payment_decision_id"]).state,
            "PREPARED",
        )

    def test_wrong_commercial_approval_never_creates_payment_authority(self):
        with self.assertRaisesRegex(Exception, "commercial-approval-mismatch"):
            self.paid.prepare_wallet(
                self.grant_id,
                commercial_approval_digest="wrong",
                payload=self.payload,
                now=NOW + 1,
            )
        self.assertEqual(self.commercial_journal.get(self.grant_id).state, "PREPARED")

    def test_invalid_payload_fails_before_commercial_approval(self):
        bad = dict(self.payload)
        bad["repository_source"] = "secret"
        with self.assertRaisesRegex(Exception, "reference-payload-field-not-authorized"):
            self.paid.prepare_wallet(
                self.grant_id,
                commercial_approval_digest=self.approval,
                payload=bad,
                now=NOW + 1,
            )
        self.assertEqual(self.commercial_journal.get(self.grant_id).state, "PREPARED")

    def test_duplicate_wallet_prepare_is_idempotent_before_dispatch(self):
        first = self.paid.prepare_wallet(
            self.grant_id,
            commercial_approval_digest=self.approval,
            payload=self.payload,
            now=NOW + 1,
        )
        second = self.paid.prepare_wallet(
            self.grant_id,
            commercial_approval_digest=self.approval,
            payload=self.payload,
            now=NOW + 1,
        )
        self.assertEqual(first["payment_decision_id"], second["payment_decision_id"])
        self.assertEqual(first["wallet_request"], second["wallet_request"])
        self.assertEqual(self.payment_journal.get(first["payment_decision_id"]).state, "PREPARED")

    def test_explicit_wallet_rejection_aborts_payment_and_commercial_grant(self):
        out = self.paid.prepare_wallet(
            self.grant_id,
            commercial_approval_digest=self.approval,
            payload=self.payload,
            now=NOW + 1,
        )
        aborted = self.paid.abort_wallet(self.grant_id, out["payment_decision_id"])
        self.assertEqual(aborted["state"], "ABORTED")
        self.assertEqual(self.payment_journal.get(out["payment_decision_id"]).state, "ABORTED")
        self.assertEqual(self.commercial_journal.get(self.grant_id).state, "ABORTED")

    def test_paid_capability_reconciles_settlement_before_execution_and_proof(self):
        out = self.paid.prepare_wallet(
            self.grant_id,
            commercial_approval_digest=self.approval,
            payload=self.payload,
            now=NOW + 1,
        )
        result = self.paid.reconcile(
            self.grant_id,
            out["payment_decision_id"],
            "0xabc123456789",
            SENDER,
            now=NOW + 2,
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["commercial_state"], "CONSUMED")
        self.assertEqual(result["payment_state"], "CONSUMED")
        self.assertEqual(result["settlement"]["amount_atomic"], 30_000)
        self.assertEqual(result["settlement"]["recipient"], RECIPIENT)
        self.assertEqual(result["action_receipt"]["settlement_digest"], result["settlement"]["digest"])
        self.assertEqual(result["verification"], {"verdict": "VERIFIED", "errors": []})
        self.assertEqual(self.commercial_journal.get(self.grant_id).state, "CONSUMED")
        self.assertEqual(self.payment_journal.get(out["payment_decision_id"]).state, "CONSUMED")

    def test_unobserved_settlement_preserves_both_authorities_in_doubt(self):
        self.paid.rpc = FakeRpc(fail=True)
        out = self.paid.prepare_wallet(
            self.grant_id,
            commercial_approval_digest=self.approval,
            payload=self.payload,
            now=NOW + 1,
        )
        with self.assertRaisesRegex(CommercialLiveError, "commercial-settlement-not-observed"):
            self.paid.reconcile(
                self.grant_id,
                out["payment_decision_id"],
                "0xabc123456789",
                SENDER,
                now=NOW + 2,
            )
        self.assertEqual(self.payment_journal.get(out["payment_decision_id"]).state, "IN_DOUBT")
        self.assertEqual(self.commercial_journal.get(self.grant_id).state, "IN_DOUBT")

    def test_consumed_paid_grant_cannot_reconcile_again(self):
        out = self.paid.prepare_wallet(
            self.grant_id,
            commercial_approval_digest=self.approval,
            payload=self.payload,
            now=NOW + 1,
        )
        self.paid.reconcile(
            self.grant_id,
            out["payment_decision_id"],
            "0xabc123456789",
            SENDER,
            now=NOW + 2,
        )
        with self.assertRaisesRegex(CommercialLiveError, "payment-reconciliation-not-allowed:CONSUMED"):
            self.paid.reconcile(
                self.grant_id,
                out["payment_decision_id"],
                "0xabc123456789",
                SENDER,
                now=NOW + 3,
            )


if __name__ == "__main__":
    unittest.main()
