from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path
from typing import Callable, Protocol

from src.model import Authority, Quote, Settlement
from src.settlement import JsonRpcClient, SettlementError, transaction_request


class ExecutionStateError(RuntimeError):
    pass


class SettlementInDoubt(ExecutionStateError):
    """Broadcast may have happened; reconciliation is required before retry."""


class Broadcaster(Protocol):
    def __call__(self, transaction: dict) -> str: ...


_ALLOWED_TRANSITIONS = {
    "PREPARED": {"DISPATCHED", "IN_DOUBT", "ABORTED"},
    "DISPATCHED": {"OBSERVED", "IN_DOUBT"},
    "IN_DOUBT": {"DISPATCHED", "OBSERVED"},
    "OBSERVED": {"CONSUMED"},
    "CONSUMED": set(),
    "ABORTED": set(),
}


@dataclass(frozen=True)
class ExecutionRecord:
    decision_id: str
    quote_digest: str
    authority_digest: str
    state: str
    transaction_hash: str | None


class ExecutionJournal:
    """Durable one-shot authority journal.

    The journal is intentionally small and local. It prevents a decision from
    being dispatched twice and preserves ambiguous outcomes as IN_DOUBT until
    independent reconciliation establishes what happened.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    decision_id TEXT PRIMARY KEY,
                    quote_digest TEXT NOT NULL,
                    authority_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    transaction_hash TEXT,
                    context_json TEXT
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(executions)")}
            if "context_json" not in columns:
                conn.execute("ALTER TABLE executions ADD COLUMN context_json TEXT")

    def reserve(self, authority: Authority, quote: Quote, *, context_json: str | None = None) -> ExecutionRecord:
        if authority.decision != "PERMIT":
            raise ExecutionStateError("execution-requires-permit")
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO executions(decision_id, quote_digest, authority_digest, state, context_json) VALUES (?, ?, ?, 'PREPARED', ?)",
                    (authority.decision_id, quote.digest, authority.digest, context_json),
                )
        except sqlite3.IntegrityError as exc:
            raise ExecutionStateError("authority-already-reserved") from exc
        return self.get(authority.decision_id)

    def context(self, decision_id: str) -> str | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT context_json FROM executions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        if row is None:
            raise ExecutionStateError("execution-not-found")
        return row["context_json"]

    def get(self, decision_id: str) -> ExecutionRecord:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT decision_id, quote_digest, authority_digest, state, transaction_hash "
                "FROM executions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        if row is None:
            raise ExecutionStateError("execution-not-found")
        return ExecutionRecord(**dict(row))

    def transition(self, decision_id: str, state: str, *, transaction_hash: str | None = None) -> ExecutionRecord:
        current = self.get(decision_id)
        if state not in _ALLOWED_TRANSITIONS.get(current.state, set()):
            raise ExecutionStateError(f"invalid-transition:{current.state}->{state}")
        if current.transaction_hash and transaction_hash and current.transaction_hash != transaction_hash:
            raise ExecutionStateError("transaction-hash-mismatch")
        tx_hash = transaction_hash or current.transaction_hash
        if state in {"DISPATCHED", "OBSERVED", "CONSUMED"} and not tx_hash:
            raise ExecutionStateError("transaction-hash-required")
        with closing(self._connect()) as conn, conn:
            changed = conn.execute(
                "UPDATE executions SET state = ?, transaction_hash = ? "
                "WHERE decision_id = ? AND state = ?",
                (state, tx_hash, decision_id, current.state),
            ).rowcount
        if changed != 1:
            raise ExecutionStateError("execution-state-race")
        return self.get(decision_id)

    def mark_dispatched(self, decision_id: str, transaction_hash: str) -> ExecutionRecord:
        return self.transition(decision_id, "DISPATCHED", transaction_hash=transaction_hash)

    def abort_prepared(self, decision_id: str) -> ExecutionRecord:
        """Close a reservation only when dispatch is known not to have occurred."""
        return self.transition(decision_id, "ABORTED")

    def mark_in_doubt(self, decision_id: str, transaction_hash: str | None = None) -> ExecutionRecord:
        return self.transition(decision_id, "IN_DOUBT", transaction_hash=transaction_hash)

    def mark_observed(self, decision_id: str, transaction_hash: str) -> ExecutionRecord:
        return self.transition(decision_id, "OBSERVED", transaction_hash=transaction_hash)

    def consume(self, decision_id: str) -> ExecutionRecord:
        return self.transition(decision_id, "CONSUMED")


@dataclass
class GovernedOnChainSettlementProvider:
    """External-wallet settlement with durable replay protection.

    AgentPay constructs the exact transaction but never receives a private key.
    The injected broadcaster is the operator-controlled signing boundary.
    Settlement truth is then reconstructed independently from Base RPC.
    """

    journal: ExecutionJournal
    broadcaster: Broadcaster
    rpc: JsonRpcClient
    expected_sender: str

    def settle(self, transaction: dict, quote: Quote, authority: Authority) -> Settlement:
        expected = transaction_request(authority, quote, now=min(authority.expires_at, quote.expires_at))
        if transaction != expected:
            raise ExecutionStateError("transaction-request-mismatch")

        self.journal.reserve(authority, quote)
        try:
            tx_hash = self.broadcaster(transaction)
            if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
                raise ExecutionStateError("broadcast-returned-invalid-hash")
        except Exception as exc:
            self.journal.mark_in_doubt(authority.decision_id)
            raise SettlementInDoubt("broadcast-outcome-unknown") from exc

        self.journal.mark_dispatched(authority.decision_id, tx_hash)
        try:
            settlement = self.rpc.observe(tx_hash, quote, self.expected_sender)
        except SettlementError as exc:
            self.journal.mark_in_doubt(authority.decision_id, tx_hash)
            raise SettlementInDoubt("settlement-not-yet-reconciled") from exc

        self.journal.mark_observed(authority.decision_id, tx_hash)
        self.journal.consume(authority.decision_id)
        return settlement
