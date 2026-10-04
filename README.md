# AgentPay Proof

Governed payments for autonomous agents.

AgentPay Proof demonstrates a narrow end-to-end machine-to-machine transaction: an agent requests a digital service, receives a quote, obtains bounded authority, settles USDC on Base, receives the service result, and produces a verifiable evidence receipt linking intent, authorization, settlement, execution, and independent observation.

## Hackathon scope

This repository contains the implementation created for the Colosseum Crypto World’s Fair hackathon. Frequency is pre-existing assurance infrastructure and remains outside this repository; AgentPay Proof integrates with it only through a bounded evidence/decision interface.

## Demo target

1. A purchase above the authority ceiling is denied before payment.
2. A permitted purchase produces a Base settlement reference.
3. The service executes.
4. An independent observation is attached.
5. A portable proof receipt verifies the complete transaction chain.

## Security properties

- deny by default
- explicit spending ceiling and recipient/service binding
- no payment before an authorization decision
- deterministic evidence hashing
- independent observation represented separately from agent claims
- no private keys or secrets committed to the repository

## Status

Initial hackathon implementation in progress.
