from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time
import uuid

from src.execution import ExecutionJournal, ExecutionStateError
from src.model import Authority, Intent, Quote, make_proof, decide
from src.observer import IndependentObserver
from src.service import QUOTE_TTL_SECONDS, SERVICE_ID, ServiceRequest, execute
from src.settlement import JsonRpcClient, SettlementError, transaction_request
from src.verifier import verify


class LivePaymentError(RuntimeError):
    pass


def _address(value: str) -> str:
    value = value.lower()
    if not value.startswith("0x") or len(value) != 42:
        raise LivePaymentError("invalid-live-address")
    int(value[2:], 16)
    return value


@dataclass(frozen=True)
class LiveConfig:
    rpc_url: str
    journal_path: str
    chain_id: int
    asset_contract: str
    recipient: str
    maximum_amount_atomic: int
    observer_id: str = "observer:agentpay-live"

    def validate(self) -> "LiveConfig":
        if not self.rpc_url.startswith(("http://", "https://")):
            raise LivePaymentError("live-rpc-required")
        if self.chain_id <= 0:
            raise LivePaymentError("live-chain-invalid")
        _address(self.asset_contract)
        _address(self.recipient)
        if self.maximum_amount_atomic <= 0:
            raise LivePaymentError("live-authority-invalid")
        return self


class LiveCoordinator:
    """Two-phase browser-wallet handoff.

    prepare() creates and durably reserves one exact payment authority before a
    wallet sees the transaction. reconcile() treats the supplied tx hash only as
    a lookup key and independently reconstructs settlement from Base RPC.
    """

    def __init__(self, config: LiveConfig):
        self.config = config.validate()
        self.journal = ExecutionJournal(config.journal_path)
        self.rpc = JsonRpcClient(config.rpc_url)
        self.observer = IndependentObserver(config.observer_id)

    def prepare(self, document: str, *, amount_atomic: int, agent_id: str,
                now: int | None = None) -> dict:
        now = int(time.time()) if now is None else now
        request = ServiceRequest(document)
        quote = Quote(
            quote_id=f"live-q-{uuid.uuid4()}",
            service_id=SERVICE_ID,
            recipient=_address(self.config.recipient),
            chain_id=self.config.chain_id,
            asset_contract=_address(self.config.asset_contract),
            amount_atomic=amount_atomic,
            expires_at=now + QUOTE_TTL_SECONDS,
            request_digest=request.digest,
        )
        intent = Intent(
            intent_id="live-intent:" + request.digest[:24],
            agent_id=agent_id,
            service_id=SERVICE_ID,
            request_digest=request.digest,
            created_at=now,
        )
        authority = decide(
            intent,
            quote,
            decision_id=f"live-decision-{uuid.uuid4()}",
            maximum_amount_atomic=self.config.maximum_amount_atomic,
            recipient=quote.recipient,
            service_id=SERVICE_ID,
            chain_id=self.config.chain_id,
            asset_contract=quote.asset_contract,
            expires_at=quote.expires_at,
            now=now,
        )
        if authority.decision == "DENY":
            proof = make_proof(intent, quote, authority)
            return {
                "environment": "LIVE",
                "status": "DENIED",
                "proof": proof,
                "verification": verify(proof, now=now),
                "wallet_request": None,
            }

        tx = transaction_request(authority, quote, now=now)
        context = json.dumps({
            "document": document,
            "agent_id": agent_id,
            "prepared_at": now,
            "intent": asdict(intent),
            "quote": asdict(quote),
            "authority": asdict(authority),
            "transaction": tx,
        }, sort_keys=True, separators=(",", ":"))
        self.journal.reserve(authority, quote, context_json=context)
        return {
            "environment": "LIVE",
            "status": "AWAITING_WALLET",
            "decision_id": authority.decision_id,
            "expires_at": authority.expires_at,
            "wallet_request": {
                "chainId": hex(tx["chain_id"]),
                "to": tx["to"],
                "value": hex(tx["value"]),
                "data": tx["data"],
            },
            "authority": {**asdict(authority), "digest": authority.digest},
            "quote": {**asdict(quote), "digest": quote.digest},
        }

    def abort(self, decision_id: str) -> dict:
        record = self.journal.abort_prepared(decision_id)
        return {"environment": "LIVE", "decision_id": decision_id, "state": record.state}

    def _context(self, decision_id: str) -> tuple[dict, Intent, Quote, Authority]:
        raw = self.journal.context(decision_id)
        if not raw:
            raise LivePaymentError("prepared-context-missing")
        data = json.loads(raw)
        return (
            data,
            Intent(**data["intent"]),
            Quote(**data["quote"]),
            Authority(**data["authority"]),
        )

    def reconcile(self, decision_id: str, tx_hash: str, sender: str,
                  *, now: int | None = None) -> dict:
        now = int(time.time()) if now is None else now
        sender = _address(sender)
        if not isinstance(tx_hash, str) or not tx_hash.startswith("0x") or len(tx_hash) < 10:
            raise LivePaymentError("transaction-hash-invalid")

        data, intent, quote, authority = self._context(decision_id)
        expected_tx = transaction_request(
            authority, quote, now=min(data["prepared_at"], authority.expires_at)
        )
        if data["transaction"] != expected_tx:
            raise LivePaymentError("prepared-transaction-corrupt")

        record = self.journal.get(decision_id)
        if record.state == "PREPARED":
            record = self.journal.mark_dispatched(decision_id, tx_hash)
        elif record.state == "IN_DOUBT" and not record.transaction_hash:
            record = self.journal.mark_dispatched(decision_id, tx_hash)
        elif record.state == "IN_DOUBT" and record.transaction_hash == tx_hash:
            pass
        elif record.state == "DISPATCHED" and record.transaction_hash == tx_hash:
            pass
        else:
            raise LivePaymentError(f"reconciliation-not-allowed:{record.state}")

        try:
            settlement = self.rpc.observe(tx_hash, quote, sender)
        except SettlementError as exc:
            current = self.journal.get(decision_id)
            if current.state == "DISPATCHED":
                self.journal.mark_in_doubt(decision_id, tx_hash)
            raise LivePaymentError("settlement-not-observed") from exc

        current = self.journal.get(decision_id)
        if current.state == "IN_DOUBT":
            current = self.journal.mark_observed(decision_id, tx_hash)
        elif current.state == "DISPATCHED":
            current = self.journal.mark_observed(decision_id, tx_hash)
        else:
            raise LivePaymentError(f"observation-not-allowed:{current.state}")

        request = ServiceRequest(data["document"])
        # Service execution is bound to the original request/quote. The dispatch
        # was authorized before expiry; reconciliation may finish later.
        artifact, result = execute(
            request, quote, now=min(data["prepared_at"], quote.expires_at)
        )
        observation = self.observer.observe(
            settlement=settlement, result=result, artifact=artifact, now=now
        )
        proof = make_proof(intent, quote, authority, settlement, result, observation)
        verification = verify(proof, now=min(now, authority.expires_at))
        if verification["verdict"] != "VERIFIED":
            raise LivePaymentError("proof-verification-failed")
        self.journal.consume(decision_id)
        return {
            "environment": "LIVE",
            "status": "VERIFIED",
            "execution_state": "CONSUMED",
            "artifact": artifact,
            "proof": proof,
            "verification": verification,
        }
