from __future__ import annotations

from dataclasses import dataclass

from src.model import Observation, ServiceResult, Settlement, canonical_hash


class ObservationError(ValueError):
    pass


@dataclass(frozen=True)
class IndependentObserver:
    observer_id: str

    def observe(self, *, settlement: Settlement, result: ServiceResult,
                artifact: dict, now: int) -> Observation:
        if not self.observer_id:
            raise ObservationError("observer-id-required")
        if settlement.status != "FINALIZED":
            raise ObservationError("settlement-not-finalized")
        if result.status != "COMPLETE":
            raise ObservationError("service-result-incomplete")
        if canonical_hash(artifact) != result.result_digest:
            raise ObservationError("result-artifact-mismatch")
        return Observation(
            observer_id=self.observer_id,
            settlement_digest=settlement.digest,
            result_digest=result.digest,
            verdict="MATCH",
            observed_at=now,
        )
