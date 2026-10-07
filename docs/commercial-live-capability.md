# Commercial Live Capability Boundary v0.1

Status: implemented, reference paid route disabled by default

This layer connects an exact Commercial Grant to the existing AgentPay external-wallet and Base settlement rail.

It does **not** give Companion custody of a wallet and it does not make reference capabilities chargeable by default.

## Full DDC/Frequency sweep findings

The pre-integration sweep identified three boundaries that had to be closed before exposing a paid capability path.

### 1. Payload substitution window

The first commercial approval bound the selected offer, but not the exact capability payload.

That is insufficient for a one-shot commercial action.

The live path now uses two approvals:

```
Commercial Plan
  ↓
Commercial approval
  ↓
Route + payload + exact transaction prepared
  ↓
Execution approval
  ↓
Wallet request released
```

The second approval digest binds:

- Commercial Grant
- Capability Route
- exact payload digest
- exact ERC-20 transaction
- human-visible execution summary

Changing any of them invalidates the approval.

### 2. Multiple payment authorities for one grant

A Commercial Grant must not be reusable to mint multiple wallet requests.

The payment decision identity is now derived from the grant itself.

Attempting to prepare the same grant with a different route or payload collides with the existing durable payment reservation and fails closed if the context differs.

### 3. Reference capability is not a real paid provider

The current `browser.render.verify` implementation is a deterministic reference adapter.

It is useful for proving the commercial authority and evidence chain, but it is not an independent external provider and must not be presented as one.

Therefore the HTTP paid route is disabled unless:

```
AGENTPAY_ENABLE_REFERENCE_PAID_CAPABILITY=1
```

Production should leave this unset.

A real paid provider must receive a separately reviewed provider binding before the gate is enabled.

## Live flow

The complete flow is:

```
Commercial Intent Capsule
→ Capability planning
→ Commercial Grant PREPARED
→ Commercial approval
→ Capability Route
→ exact payload binding
→ exact payment authority
→ execution approval
→ wallet request
→ user signs externally
→ Base transaction
→ independent RPC reconstruction
→ capability dispatch
→ action receipt
→ outcome assessment
→ Commercial Proof
→ CONSUMED
```

No private key enters AgentPay.

## Capability Route

A Capability Route binds:

- selected offer digest
- provider
- capability
- adapter ID
- request schema
- observation schema
- Base chain ID
- USDC token contract
- payment recipient
- exact payment amount
- expiry

The current reference resolver accepts only:

- provider: `provider:render-only`
- capability: `browser.render.verify`
- settlement asset: `USDC`

Arbitrary provider URLs are not accepted.

## Wallet handoff

`POST /api/commercial/live/prepare`

Validates the commercial approval and reserves one exact payment authority.

It returns:

- route
- payment decision ID
- exact quote
- execution HIO summary
- execution approval digest

It deliberately returns:

```
wallet_request: null
```

until the execution approval is confirmed.

`POST /api/commercial/live/confirm`

Requires the exact execution approval digest.

Only then does it return the wallet request.

The confirmation also fails if the route/payment authority has expired.

## Wallet rejection and uncertainty

`POST /api/commercial/live/abort`

is allowed only while dispatch is known not to have happened.

It aborts both the payment authority and the commercial grant.

`POST /api/commercial/live/uncertain`

moves both boundaries to `IN_DOUBT`.

No automatic retry is allowed.

## Settlement reconciliation

`POST /api/commercial/live/reconcile`

takes the transaction hash only as a lookup key.

AgentPay independently reconstructs:

- Base chain
- sender
- USDC token contract
- recipient
- calldata
- transfer amount
- matching Transfer log
- finalized status

Only a matching observed settlement permits capability execution.

## Paid capability receipt

The paid capability receipt binds:

- Commercial Grant
- Capability Route
- provider
- capability
- payment authority
- quote
- independently observed settlement
- returned artifact
- underlying execution receipt
- evidence types

The final Commercial Proof references the paid action proof hash.

The cross-object verifier then re-binds:

```
Capsule
Plan
Offer
Grant
Paid Action Receipt
Artifact
Outcome Assessment
Commercial Proof
```

before the commercial grant is consumed.

## Important direct ERC-20 limitation

The current wallet rail uses a normal ERC-20 `transfer`.

The server prevents release of a wallet request after authority expiry, but a normal ERC-20 transfer does not contain an on-chain deadline.

Therefore:

- this rail is suitable only for explicit human wallet approval
- it must not be treated as cryptographically expiring autonomous authority
- unattended commercial execution remains disabled

A future autonomous settlement rail should use a deadline-enforcing primitive, such as a purpose-built escrow/payment contract or an authorization mechanism with an enforceable validity window.

That limitation is part of the protocol evidence and must not be hidden by HIO.

## Provider admission requirements

Before a real external paid capability is enabled, its adapter must bind:

- provider identity
- recipient identity
- capability
- request schema
- response schema
- disclosure manifest
- data-retention terms
- idempotency behavior
- cancellation semantics
- evidence format
- observation mechanism
- settlement terms
- route expiry
- independent health/availability evidence

Provider discovery must not itself grant authority.

## Production invariant

The existence of a configured Base wallet recipient does not make a capability commercially valid.

A route must independently satisfy:

```
Commercial Intent
+ Offer
+ Grant
+ Provider Binding
+ Route
+ Execution Approval
+ Wallet Approval
+ Settlement Observation
+ Outcome Evidence
```

Only then can the commercial action become VERIFIED.
