import unittest

from src.x402 import EIP3009Authorization, X402Requirement
from src.x402_local_verify import verify_eip3009_locally


NOW = 1_800_000_000
PAYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"
TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
NONCE = "0x" + "33" * 32
SIG = "0x" + "11" * 32 + "22" * 32 + "1b"


def requirement():
    return X402Requirement(
        resource_url="https://agentpay.example/api/x402/code-analysis",
        scheme="exact",
        network="eip155:8453",
        amount=250000,
        asset=TOKEN,
        pay_to=PAYEE,
        max_timeout_seconds=60,
        token_name="USD Coin",
        token_version="2",
    )


def authorization():
    return EIP3009Authorization(
        from_address=PAYER,
        to=PAYEE,
        value=250000,
        valid_after=NOW - 1,
        valid_before=NOW + 60,
        nonce=NONCE,
    )


class FakeRpc:
    def __init__(self, *, balance=1_000_000, used=False, chain=8453, code="0x6000", simulation_error=False):
        self.balance = balance
        self.used = used
        self.chain = chain
        self.code = code
        self.simulation_error = simulation_error
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "eth_chainId":
            return hex(self.chain)
        if method == "eth_getCode":
            return self.code
        if method == "eth_call":
            data = params[0]["data"]
            if data.startswith("0x70a08231"):
                return hex(self.balance)
            if data.startswith("0xe94a0102"):
                return hex(1 if self.used else 0)
            if data.startswith("0xe3ee160e"):
                if self.simulation_error:
                    raise RuntimeError("execution reverted")
                return "0x"
        raise AssertionError((method, params))


class LocalVerifyTests(unittest.TestCase):
    def test_valid_authorization_is_verified_without_facilitator(self):
        rpc = FakeRpc()
        result = verify_eip3009_locally(
            rpc,
            requirement(),
            authorization(),
            SIG,
            now=NOW,
            recover_address=lambda requirement, authorization, signature: PAYER,
        )
        self.assertEqual(result.verdict, "VERIFIED")
        self.assertFalse(result.authorization_used)
        self.assertEqual(result.balance_atomic, 1_000_000)
        self.assertTrue(result.digest)

    def test_transfer_simulation_revert_fails_closed(self):
        result = verify_eip3009_locally(
            FakeRpc(simulation_error=True),
            requirement(),
            authorization(),
            SIG,
            now=NOW,
            recover_address=lambda requirement, authorization, signature: PAYER,
        )
        self.assertEqual(result.verdict, "NOT VERIFIED")
        self.assertFalse(result.transfer_simulation_ok)
        self.assertIn("transfer-with-authorization-simulation-failed", result.reasons)

    def test_used_authorization_fails_closed(self):
        result = verify_eip3009_locally(
            FakeRpc(used=True),
            requirement(),
            authorization(),
            SIG,
            now=NOW,
            recover_address=lambda requirement, authorization, signature: PAYER,
        )
        self.assertEqual(result.verdict, "NOT VERIFIED")
        self.assertIn("authorization-already-used", result.reasons)

    def test_insufficient_balance_fails_closed(self):
        result = verify_eip3009_locally(
            FakeRpc(balance=249999),
            requirement(),
            authorization(),
            SIG,
            now=NOW,
            recover_address=lambda requirement, authorization, signature: PAYER,
        )
        self.assertEqual(result.verdict, "NOT VERIFIED")
        self.assertIn("insufficient-balance", result.reasons)

    def test_wrong_signer_fails_closed(self):
        result = verify_eip3009_locally(
            FakeRpc(),
            requirement(),
            authorization(),
            SIG,
            now=NOW,
            recover_address=lambda requirement, authorization, signature: PAYEE,
        )
        self.assertEqual(result.verdict, "NOT VERIFIED")
        self.assertIn("signature-payer-mismatch", result.reasons)

    def test_wrong_chain_and_missing_contract_fail_closed(self):
        result = verify_eip3009_locally(
            FakeRpc(chain=1, code="0x"),
            requirement(),
            authorization(),
            SIG,
            now=NOW,
            recover_address=lambda requirement, authorization, signature: PAYER,
        )
        self.assertEqual(result.verdict, "NOT VERIFIED")
        self.assertIn("chain-mismatch", result.reasons)
        self.assertIn("asset-contract-code-missing", result.reasons)


if __name__ == "__main__":
    unittest.main()
