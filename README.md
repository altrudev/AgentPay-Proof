# AgentPay Proof

Governed payments for autonomous agents.

AgentPay Proof demonstrates a narrow end-to-end machine-to-machine transaction: an agent requests a digital service, receives a quote, obtains bounded authority, settles USDC on Base, receives the service result, and produces a verifiable evidence receipt linking intent, authorization, settlement, execution, and independent observation.

## Hackathon scope

This repository contains the implementation created for the Colosseum Crypto World’s Fair hackathon. Frequency is pre-existing assurance infrastructure and remains outside this repository; AgentPay Proof integrates with it only through a bounded evidence/decision interface.

## Demo target

1. A purchase above the authority ceiling is denied before payment.
2. A permitted purchase produces an exact Base USDC transaction request.
3. An operator-controlled wallet signs/broadcasts it without exposing private keys to AgentPay Proof.
4. AgentPay independently reconstructs the settlement from Base RPC evidence.
5. The service executes.
6. A distinct observer binds settlement and service-result evidence.
7. A portable proof receipt verifies the complete transaction chain.
8. Mutation or authority replay produces NOT VERIFIED / execution rejection.

## Execution safety

AgentPay Proof uses a durable execution journal for one-shot payment authority. A permitted decision moves through:

`PREPARED -> DISPATCHED -> OBSERVED -> CONSUMED`

If broadcast or settlement observation becomes ambiguous, the state becomes `IN_DOUBT`. AgentPay does not silently retry an ambiguous payment. Reconciliation must establish the chain outcome first.

This protects against the dangerous failure mode where a client times out after broadcast, assumes failure, and pays again.

## Security properties

- deny by default
- explicit spending ceiling and recipient/service binding
- no payment before an authorization decision
- one-shot durable authority consumption
- ambiguous dispatch is fail-closed as `IN_DOUBT`
- deterministic evidence hashing
- independent Base RPC settlement reconstruction
- independent observation represented separately from agent claims
- no private keys or secrets committed to the repository
- operator-controlled signing boundary

## Run tests

```bash
python -m unittest discover -s tests -v
```

## Status

Hackathon implementation in progress. The deterministic/demo path and verification core are implemented. Real-value competition readiness still requires a live operator-wallet Base USDC transaction to be demonstrated end to end.

## License

Apache-2.0.
