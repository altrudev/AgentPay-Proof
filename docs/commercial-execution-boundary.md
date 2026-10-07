# Commercial Execution Boundary v0.1

This layer takes the commercial plan produced by Companion and turns it into a one-shot, replay-resistant commercial grant.

It deliberately separates:

**proposal → grant projection → approval → dispatch → observation → outcome assessment → proof → consumption**

The planner never receives execution authority merely because it selected an offer.

## State machine

```
PREPARED
  ├─ APPROVED
  │    ├─ DISPATCHED
  │    │    ├─ OBSERVED
  │    │    │    └─ CONSUMED
  │    │    └─ IN_DOUBT
  │    └─ IN_DOUBT
  └─ ABORTED
```

A consumed or aborted grant has no outgoing transitions.

IN_DOUBT is intentionally durable. It prevents an ambiguous commercial action from being silently retried.

## Commercial Grant

A grant binds:

- capsule digest
- plan digest
- selected offer digest and ID
- provider
- capability
- exact price
- settlement asset
- exact disclosures
- required evidence
- credential lifetime
- compute limit
- retention limit
- expiry
- automatic-execution flag

The grant is projected only after the selected offer independently passes the commercial envelope.

The planner cannot substitute a different provider or offer after selection.

## Approval binding

Human approval is not a boolean.

The approval digest is a canonical hash of:

- the exact grant digest
- the exact HIO explanation surface

Changing the provider, price, disclosures, evidence, retention, confidence, or another displayed decision fact changes the approval digest.

This prevents approval for one commercial action from being reused for a materially different action.

## Dispatch boundary

Reference execution accepts only fields authorized by the reference capability schema.

Unknown fields fail closed.

The current reference adapter is deterministic and non-monetary. It exists to validate the authority and evidence architecture before a real external provider adapter is allowed to settle value.

Real USDC spending continues to require the existing external-wallet boundary.

## Independent evidence bundle verification

Before a commercial execution is consumed, the verifier re-binds all of these objects independently:

- Intent Capsule
- Commercial Plan
- selected Capability Offer
- Commercial Grant
- Action Receipt
- returned artifact
- Outcome Assessment
- Commercial Proof

The verifier checks all cross-object digests rather than trusting the outer proof hash alone.

This catches:

- substituted artifact
- substituted provider
- substituted capability
- modified disclosure evidence
- modified confidence result
- modified plan
- modified grant
- modified outcome
- modified action receipt
- modified final proof

## Reference API

`GET /api/commercial/prepare-demo`

Creates a reference plan and durable PREPARED grant. It does not execute anything.

`POST /api/commercial/execute-demo`

Requires:

- grant ID
- exact approval digest
- rendered-page digest
- reference digest

The reference adapter executes only after exact approval and returns:

- action receipt
- artifact
- independent outcome assessment
- Commercial Proof
- full verification result

The response explicitly states:

`monetary_settlement: NOT_PERFORMED`

## Current security invariants

1. Companion can propose but cannot manufacture authority.
2. Planning cannot dispatch.
3. Preparation cannot dispatch.
4. Approval is bound to exact human-visible commercial facts.
5. One grant can be consumed only once.
6. Unknown payload fields fail closed.
7. Expired grants cannot execute.
8. Unsafe offers produce no grant.
9. Ambiguous execution becomes IN_DOUBT.
10. Final consumption requires a verified cross-object evidence bundle.
11. The reference commercial path cannot spend real funds.
12. Existing wallet approval remains the boundary for real Base/USDC settlement.

## Next adapter boundary

A real commercial capability adapter must provide:

- provider identity binding
- provider endpoint/capability binding
- exact request schema
- purpose-bound credential
- disclosure manifest
- settlement requirement
- independent result observation
- evidence receipt
- retry/idempotency semantics
- cancellation/expiry behavior

No external provider adapter should be enabled until it can satisfy these invariants.
