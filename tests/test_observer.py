import unittest

from src.model import ServiceResult, Settlement, canonical_hash
from src.observer import IndependentObserver, ObservationError


class ObserverTests(unittest.TestCase):
    def test_tampered_artifact_is_rejected(self):
        artifact = {"value": "original"}
        result = ServiceResult("svc", "req", canonical_hash(artifact), "COMPLETE")
        settlement = Settlement(8453, "0xabc", "0xsender", "0xrecipient", "0xtoken", 1, "FINALIZED")
        with self.assertRaisesRegex(ObservationError, "result-artifact-mismatch"):
            IndependentObserver("observer").observe(
                settlement=settlement,
                result=result,
                artifact={"value": "tampered"},
                now=1,
            )

    def test_unfinalized_settlement_is_rejected(self):
        artifact = {"value": "ok"}
        result = ServiceResult("svc", "req", canonical_hash(artifact), "COMPLETE")
        settlement = Settlement(8453, "0xabc", "s", "r", "t", 1, "PENDING")
        with self.assertRaisesRegex(ObservationError, "settlement-not-finalized"):
            IndependentObserver("observer").observe(
                settlement=settlement, result=result, artifact=artifact, now=1
            )


if __name__ == "__main__":
    unittest.main()
