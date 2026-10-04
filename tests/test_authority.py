import copy
import unittest

from src.demo import run
from src.verifier import verify


class ProofVerifierTests(unittest.TestCase):
    def test_over_limit_is_verified_denial_without_settlement(self):
        proof = run(2_000_000)
        self.assertIsNone(proof["settlement"])
        self.assertEqual(verify(proof, now=1_800_000_001)["verdict"], "VERIFIED DENIAL")

    def test_complete_fixture_verifies(self):
        proof = run(250_000)
        self.assertEqual(verify(proof, now=1_800_000_001), {"verdict": "VERIFIED", "errors": []})

    def test_tampered_recipient_is_not_verified(self):
        proof = run(250_000)
        proof["settlement"]["recipient"] = "0x000000000000000000000000000000000000BAD0"
        verdict = verify(proof, now=1_800_000_001)
        self.assertEqual(verdict["verdict"], "NOT VERIFIED")
        self.assertIn("proof-hash-mismatch", verdict["errors"])

    def test_amount_substitution_is_not_verified_even_if_outer_hash_recomputed(self):
        proof = run(250_000)
        proof["settlement"]["amount_atomic"] = 500_000
        from src.model import canonical_hash
        body = dict(proof)
        body.pop("proof_hash")
        proof["proof_hash"] = canonical_hash(body)
        verdict = verify(proof, now=1_800_000_001)
        self.assertEqual(verdict["verdict"], "NOT VERIFIED")
        self.assertIn("settlement-digest-mismatch", verdict["errors"])

    def test_replay_is_rejected(self):
        proof = run(250_000)
        verdict = verify(proof, now=1_800_000_001, consumed_decisions={"decision-demo"})
        self.assertEqual(verdict["verdict"], "NOT VERIFIED")
        self.assertIn("authority-replay", verdict["errors"])

    def test_missing_observation_is_not_verified(self):
        proof = run(250_000)
        proof["observation"] = None
        from src.model import canonical_hash
        body = dict(proof)
        body.pop("proof_hash")
        proof["proof_hash"] = canonical_hash(body)
        verdict = verify(proof, now=1_800_000_001)
        self.assertEqual(verdict["verdict"], "NOT VERIFIED")
        self.assertIn("incomplete-evidence", verdict["errors"])

    def test_self_observation_is_not_independent(self):
        proof = run(250_000)
        proof["observation"]["observer_id"] = proof["intent"]["agent_id"]
        from src.model import canonical_hash
        body = dict(proof)
        body.pop("proof_hash")
        proof["proof_hash"] = canonical_hash(body)
        verdict = verify(proof, now=1_800_000_001)
        self.assertEqual(verdict["verdict"], "NOT VERIFIED")


if __name__ == "__main__":
    unittest.main()
