# x402 v2 Exact / EIP-3009 Commercial Authority Rail

Status: implemented protocol and execution kernel; not enabled in production.

This rail replaces immediate ERC-20 transfer semantics with a bounded one-time payment authorization for providers that support x402 v2 `exact` on EVM using EIP-3009.

## Why this rail exists

The legacy direct ERC-20 path moves value when the user submits the wallet transaction. Its application-side expiry cannot make an already-created ERC-20 transfer cryptographically expire.

EIP-3009 changes the authority primitive. The payer signs an authorization containing:

- exact payer
- exact payee
- exact amount
- exact token contract through the EIP-712 domain
- exact chain through the EIP-712 domain
- `validAfter`
- `validBefore`
- unique 32-byte nonce

The facilitator pays gas and may submit the authorization only inside that validity window. The token contract enforces one-time nonce consumption.

AgentPay never receives the payer's private key.

## DDC / Frequency ordering

For the x402 v2 default `authorization` flow, AgentPay enforces:

```
Commercial Intent
→ Capability Offer
→ Provider Admission
→ Commercial Grant
→ provider PaymentRequired
→ exact x402 requirement selection
→ EIP-3009 authorization construction
→ HIO execution approval
→ wallet eth_signTypedData_v4
→ facilitator /verify
→ resource dispatch
→ resource result persisted
→ facilitator /settle
→ independent Base observation
→ outcome assessment
→ Commercial Proof
→ CONSUMED
```

Funds do not move before the resource executes.

A failed resource execution never calls settlement.

## PaymentRequired binding

AgentPay accepts exactly one matching payment requirement.

It binds:

- `x402Version = 2`
- scheme `exact`
- network `eip155:8453`
- admitted provider resource URL
- exact Commercial Grant price
- Base USDC token contract
- admitted provider settlement recipient
- `assetTransferMethod = eip3009`
- `paymentFlow = authorization`
- maximum authorization timeout <= 300 seconds
- token EIP-712 domain

For Base mainnet USDC at:

`0x833589fcd6edb6e08f4c7c32d4f71b54bda02913`

the current rail additionally fixes the EIP-712 domain to:

- name: `USD Coin`
- version: `2`

A different domain fails before a wallet signature is requested.

Multiple otherwise matching requirements also fail closed rather than allowing ambiguous selection.

## Two approvals remain

The existing Commercial Grant approval is not enough to release a wallet request.

AgentPay first creates the exact x402 authorization and HIO surface. A second execution approval digest binds:

- Commercial Grant
- Capability Route
- x402 requirement
- EIP-3009 authorization
- capability payload
- human-visible summary

Only after that digest is confirmed does AgentPay return:

`eth_signTypedData_v4`

It does not return an `eth_sendTransaction` request.

## Provider revocation timing

Admission is checked:

1. while preparing the x402 route
2. before releasing the typed-signature request
3. after signature release and immediately before facilitator verification/resource execution

If a provider is revoked before resource dispatch, execution stops.

After resource execution, the already-approved provider snapshot is frozen for settlement/reconciliation. This avoids creating a delivered-but-unsettleable action merely because registry state changes after the provider has performed the work.

## x402 state machine

```
PREPARED
  → SIGNING
  → VERIFIED
  → RESOURCE_DISPATCHED
  → RESOURCE_EXECUTED
  → SETTLEMENT_PENDING
  → SETTLED
  → OBSERVED
  → CONSUMED
```

Ambiguous side effects enter:

`IN_DOUBT`

Terminal pre-side-effect rejection can enter:

`ABORTED`

### Semantics

- `PREPARED`: exact route/requirement/nonce persisted; no wallet request released
- `SIGNING`: exact EIP-712 request released to wallet
- `VERIFIED`: facilitator read-only verification accepted the signature
- `RESOURCE_DISPATCHED`: resource execution may have begun
- `RESOURCE_EXECUTED`: result is durably stored; it must not be executed again
- `SETTLEMENT_PENDING`: a state-committing facilitator call may be in flight
- `SETTLED`: facilitator reported a transaction hash
- `OBSERVED`: independent Base evidence matched
- `CONSUMED`: commercial proof verified and one-shot authority closed
- `IN_DOUBT`: do not repeat the side effect; reconcile evidence only

## Settlement pending

x402 permits a facilitator to return `settlement_pending` with a transaction hash when a transaction may have been broadcast but confirmation cannot yet be established.

AgentPay converts that to:

```
IN_DOUBT
retry: reconcile-only
```

It does not:

- execute the resource again
- request another signature
- call settle again automatically
- mint another nonce

Once the transaction hash exists, only independent reconciliation is allowed.

## Independent Base observation

A facilitator settlement response is not sufficient for Commercial Proof.

AgentPay queries its configured Base RPC and requires one successful transaction to the expected USDC token contract containing both:

1. `AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce)`
   - exact payer
   - exact EIP-3009 nonce

2. ERC-20 `Transfer(address indexed from, address indexed to, uint256 value)`
   - exact payer
   - exact admitted provider recipient
   - exact authorized amount

Both events must be emitted by the expected token contract in the same successful transaction.

This prevents a facilitator response from being treated as settlement merely because it contains a plausible transaction hash.

## EIP-712 wallet request

The typed data uses:

```
EIP712Domain(
  string name,
  string version,
  uint256 chainId,
  address verifyingContract
)

TransferWithAuthorization(
  address from,
  address to,
  uint256 value,
  uint256 validAfter,
  uint256 validBefore,
  bytes32 nonce
)
```

The wallet signs the canonical authorization. AgentPay stores the signature only as payment authorization evidence needed for x402 verification/settlement; it never receives or stores a private key.

## Journal self-consistency

Every phase re-binds the persisted context:

- route digest
- requirement digest
- authorization digest
- capability-payload digest
- Provider Binding digest
- Provider Admission digest
- exact route/requirement chain, token, payee and amount
- authorization/requirement payee and amount
- execution approval digest

A mutated context cannot silently proceed to verification or settlement.

## Current implementation boundary

This change implements:

- x402 v2 exact/EIP-3009 requirement parsing
- exact safe requirement selection
- one-time expiring authorization generation
- typed-data wallet request
- facilitator interface
- read-only verification gate
- verify → resource → settle ordering
- durable x402 execution journal
- settlement-pending / reconcile-only behavior
- nonce-bound independent Base observation
- Commercial Proof integration

It does **not** yet:

- configure a real x402 facilitator
- admit a real external x402 provider
- expose an untrusted provider URL directly to the browser
- automatically discover x402 providers
- move real funds in tests
- enable this rail in production

Those omissions are intentional. A real facilitator and real provider need independently reviewed bindings before the production gate can be opened.

## Relationship to legacy direct ERC-20 rail

The direct ERC-20 path remains available for explicit human-wallet flows and existing compatibility tests.

For admitted x402-capable providers, EIP-3009 is the preferred future rail because it gives Frequency an on-chain-enforced one-time nonce and validity window while preserving post-resource settlement.
