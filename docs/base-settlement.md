# Base settlement boundary

AgentPay Proof separates **authority**, **transaction construction**, **signing/broadcast**, and **independent settlement observation**.

The authority layer produces an exact ERC-20 transaction request only after a PERMIT. It binds chain ID, token contract, recipient, amount, quote digest and authority digest. AgentPay Proof does not accept a transaction hash as proof.

## Operator-controlled signing

Private-key custody is intentionally outside AgentPay Proof. The execution provider accepts an injected broadcaster representing an operator-controlled wallet boundary. AgentPay supplies the exact authorized transaction request; the wallet signs and broadcasts it.

The private key is never passed into AgentPay Proof, written to the proof, or stored in the execution journal.

## Durable one-shot authority

Before invoking the wallet boundary, AgentPay durably reserves the decision ID in a local SQLite execution journal.

Normal state progression:

`PREPARED -> DISPATCHED -> OBSERVED -> CONSUMED`

A decision ID can be reserved only once. Reusing the same authority is rejected before another broadcast.

If the wallet call times out, raises after possible broadcast, or independent RPC observation cannot yet establish settlement, the execution is preserved as:

`IN_DOUBT`

An in-doubt payment is never treated as a clean failure and is never automatically retried. Reconciliation must first determine whether the authorized transfer reached the chain.

## Independent settlement observation

After broadcast, the observer fetches the transaction and receipt from a Base JSON-RPC endpoint and requires:

- successful receipt status
- expected Base chain ID
- expected sender
- exact configured token contract
- ERC-20 `Transfer` event
- exact authorized recipient
- exact quote amount

Only then is a `FINALIZED` settlement evidence object produced.

The transaction hash is therefore a lookup key, not proof by itself.

## Network

Base mainnet chain ID is 8453. Token addresses are configuration/evidence values and must be verified against the intended environment before any real-value transaction.

The repository currently uses the Base USDC contract in the deterministic service fixture. Real-value execution requires explicit operator approval and a funded operator wallet outside the repository.
