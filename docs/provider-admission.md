# Provider Admission Gate v0.1

Status: implemented; no real external provider admitted

A commercial provider is not payable merely because it exposes an endpoint or publishes a Capability Offer.

Provider admission is a separate, versioned trust decision that must succeed before a Commercial Grant can be projected onto a paid Capability Route.

## Provider Binding

A binding canonically commits to:

- provider ID
- legal/provider identity label
- capability
- adapter ID
- request schema
- response schema
- observation schema
- settlement recipient
- settlement asset
- disclosures the provider is allowed to receive
- maximum retention
- required evidence types
- idempotency model
- cancellation model
- observation model
- jurisdiction
- validity window
- version

The binding has its own digest.

## Admission policy

The current policy fails closed unless all of the following hold:

- binding is inside its validity window
- settlement asset is USDC
- retention is zero
- evidence includes:
  - execution receipt
  - result observation
  - settlement observation
- idempotency uses an admitted model
- cancellation semantics are declared
- independent observation semantics are declared

Admission produces a second digest over the admission decision.

No Capability Route can be built without both binding and admission digests.

## Versioning

Provider versions must increase monotonically.

Re-submitting the same or older version is rejected.

This prevents a stale provider definition from silently replacing a newer reviewed binding.

## Revocation

Admission can be revoked before wallet handoff.

The live path checks admission at:

1. paid route preparation
2. final execution approval / wallet release

If the provider is revoked between those stages, the wallet request is never released.

Once the wallet request has been released, a transaction may already have been signed or broadcast. From that point, reconciliation uses the frozen provider binding/admission snapshot that was approved with the transaction.

This is intentional:

- pre-dispatch revocation blocks execution
- post-dispatch revocation does not strand a transaction that may already have moved value
- the exact admitted provider snapshot remains in the evidence chain

## Recipient binding

Provider admission binds the provider's settlement recipient.

The route refuses to use a configured wallet recipient that differs from the admitted provider recipient.

This prevents a generic server configuration change from silently redirecting commercial settlement.

## Disclosure binding

A provider binding declares which disclosure classes it can receive.

A Commercial Grant cannot route through a provider if the grant requires disclosures outside that binding.

The provider cannot gain additional data authority merely because the user approved payment.

## Reference fixture

The repository includes a deterministic reference-only provider binding for tests.

Its legal identity string explicitly identifies it as:

`REFERENCE-ONLY / AgentPay test fixture`

It is not evidence of an external provider relationship.

Production paid use of the reference route remains disabled unless the separate test gate is explicitly enabled.

## Real provider admission

A real provider should not be admitted from a browser request.

Admission should come from reviewed persistent configuration or a signed provider manifest and should include independently checked evidence for:

- identity / entity ownership
- payment recipient ownership
- endpoint ownership
- capability behavior
- retention policy
- disclosure contract
- idempotency behavior
- cancellation behavior
- result observation
- evidence format
- service availability
- jurisdictional facts relied on by policy

Provider discovery and provider admission remain separate operations.

## DDC/Frequency invariant

The commercial path now requires:

```
Intent Capsule
+ Capability Offer
+ Commercial Grant
+ Provider Binding
+ Provider Admission
+ Capability Route
+ Execution Approval
+ Wallet Approval
+ Settlement Observation
+ Outcome Evidence
```

Removing any one of these prevents a VERIFIED paid commercial action.
