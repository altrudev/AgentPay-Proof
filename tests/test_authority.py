import unittest

from src.model import Intent, decide
from src.demo import run


class AuthorityTests(unittest.TestCase):
    def test_over_limit_denied_before_settlement(self):
        receipt = run("2.00")
        self.assertEqual(receipt["authority"]["decision"], "DENY")
        self.assertIsNone(receipt["settlement"])

    def test_permitted_demo_has_observation(self):
        receipt = run("0.50")
        self.assertEqual(receipt["authority"]["decision"], "PERMIT")
        self.assertEqual(receipt["settlement"]["chain"], "base")
        self.assertEqual(receipt["observation"]["outcome"], "MATCH")

    def test_wrong_recipient_denied(self):
        intent = Intent("a", "svc", "0xBad", "0.10")
        self.assertEqual(decide(intent, "1.00", "0xGood", "svc").decision, "DENY")


if __name__ == "__main__":
    unittest.main()
