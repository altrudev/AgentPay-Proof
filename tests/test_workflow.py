import unittest

from src.model import Settlement
from src.observer import IndependentObserver
from src.service import ServiceRequest
from src.workflow import AgentPayWorkflow


class FakeObservedSettlement:
    def __init__(self):
        self.calls = 0

    def settle(self, transaction, quote, authority):
        self.calls += 1
        self.last_transaction = transaction
        return Settlement(
            chain_id=quote.chain_id,
            transaction_hash="fixture:observed",
            sender="0x000000000000000000000000000000000000cafe",
            recipient=quote.recipient,
            asset_contract=quote.asset_contract,
            amount_atomic=quote.amount_atomic,
            status="FINALIZED",
        )


class WorkflowTests(unittest.TestCase):
    NOW = 1_800_000_000

    def workflow(self, provider):
        return AgentPayWorkflow(
            settlement_provider=provider,
            observer=IndependentObserver("observer:separate-process"),
            maximum_amount_atomic=1_000_000,
        )

    def test_denial_never_invokes_settlement_provider(self):
        provider = FakeObservedSettlement()
        outcome = self.workflow(provider).purchase(
            ServiceRequest("One. Two."), agent_id="agent:a", now=self.NOW,
            quote_amount_atomic=2_000_000,
        )
        self.assertEqual(outcome["status"], "DENIED")
        self.assertEqual(provider.calls, 0)
        self.assertIsNone(outcome["transaction_request"])
        self.assertEqual(outcome["verification"]["verdict"], "VERIFIED DENIAL")

    def test_permitted_purchase_runs_complete_chain(self):
        provider = FakeObservedSettlement()
        outcome = self.workflow(provider).purchase(
            ServiceRequest("One. Two. Three."), agent_id="agent:a", now=self.NOW
        )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(outcome["status"], "VERIFIED")
        self.assertEqual(outcome["verification"], {"verdict": "VERIFIED", "errors": []})
        self.assertEqual(outcome["artifact"]["summary"], "One. Two.")

    def test_observer_is_distinct_from_agent(self):
        provider = FakeObservedSettlement()
        outcome = self.workflow(provider).purchase(
            ServiceRequest("One."), agent_id="agent:a", now=self.NOW
        )
        self.assertNotEqual(
            outcome["proof"]["observation"]["observer_id"],
            outcome["proof"]["intent"]["agent_id"],
        )


if __name__ == "__main__":
    unittest.main()
