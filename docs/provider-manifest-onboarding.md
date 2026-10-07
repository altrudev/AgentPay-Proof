# Provider Manifest Onboarding v0.1

Status: implemented trust/onboarding kernel; no external provider admitted.

A provider is not admitted from discovery, a browser request, an API URL, or a Capability Offer. Real admission begins with a canonical provider manifest and independently verifiable evidence.

## Trust chain

The onboarding path is:

```
Provider Binding
→ independent evidence package
→ canonical Provider Manifest
→ detached Ed25519 signature
→ trusted issuer lookup
→ independent evidence verification
→ provider admission policy
→ durable registry write
→ runtime Provider Registry
→ paid Capability Route
```

Every transition is fail-closed.

## Canonical Provider Manifest

A manifest binds:

- provider ID
- exact Provider Binding
- manifest ID
- provider signing-key ID
- identity-control evidence
- settlement-recipient-control evidence
- endpoint-control evidence
- issue time
- expiry
- detached signature

The signature covers the canonical manifest digest without the signature field itself.

## Cryptography

The reference verifier uses Ed25519 via the `cryptography` package. It verifies a detached signature over the ASCII canonical manifest digest.

The dependency is optional at package level:

```
pip install .[provider]
```

If a runtime does not have an approved signature verifier, provider verification returns `NOT VERIFIED`. There is no unsigned fallback.

No custom cryptographic primitive is implemented by AgentPay.

## Independent evidence

A provider signature proves control of a provider signing key. It does **not** prove legal identity, wallet ownership, or endpoint ownership.

Those are separate evidence classes:

- `identity-control`
- `recipient-control`
- `endpoint-control`

Each evidence class requires its own verifier supplied by the admission environment. If a verifier is absent, admission fails closed.

The current data model records:

- evidence type
- provider subject
- independent issuer/observer
- externally meaningful reference
- observation time
- expiry
- evidence artifact digest

AgentPay does not interpret an arbitrary provider-supplied string as independent evidence.

## Recipient control

The independently verified recipient-control evidence must name the exact settlement address in the Provider Binding.

That Provider Binding recipient must later match the Capability Route and configured settlement destination before a wallet request can be released.

This gives the payment recipient a chain of evidence:

```
recipient-control evidence
→ signed Provider Manifest
→ Provider Binding
→ Provider Admission
→ Capability Route
→ Quote
→ Authority
→ observed settlement
```

## Endpoint control

Endpoint/control evidence must bind the adapter identifier admitted for the provider. A provider cannot sign one endpoint and receive authority for an unrelated adapter.

A later network adapter must still perform its own TLS, request-schema, response-schema, idempotency, and observation checks. Manifest admission is necessary but not sufficient for execution.

## Durable registry

`ProviderRegistryStore` persists admitted provider state in SQLite with:

- provider ID
- monotonically increasing version
- ACTIVE / REVOKED state
- manifest digest
- binding digest
- admission digest
- canonical manifest material
- admission material
- update/revocation time
- append-only admission/revocation history

On reload, AgentPay verifies row digests against reconstructed objects and re-verifies the manifest signature and independent evidence before restoring the exact stored admission object.

This preserves the original `admitted_at` and admission digest across process restarts.

Expired providers are omitted from the runtime registry. They do not gain authority and do not prevent unrelated valid providers from loading.

## Version and key continuity

Binding versions must increase monotonically.

For v0.1, a provider signing key cannot change during a version update. A changed `issuer_key_id` fails with:

`provider-key-rotation-not-authorized`

That is intentional. Key rotation needs its own cross-signed or independently observed protocol; silently accepting a different trusted key would weaken provider continuity.

## Revocation

Revocation is durable. A revoked provider is absent from the runtime registry after restart.

The existing live-commercial rule remains:

- revocation before wallet handoff blocks wallet release
- after wallet handoff may have occurred, the frozen approved provider snapshot is used for reconciliation so a possibly-paid transaction is not stranded

## Database tamper handling

The persistent registry does not trust SQLite contents merely because they are local.

For an active provider it checks:

- stored manifest digest equals reconstructed manifest digest
- stored binding digest equals reconstructed binding digest
- stored admission digest equals reconstructed admission digest
- manifest signature still verifies
- independent evidence still verifies
- admission still satisfies current provider policy

A mismatch fails closed.

## What is deliberately not implemented yet

This change does not pretend to establish a real provider relationship. It does not:

- admit an external company
- generate provider identity evidence
- prove ownership of somebody else's wallet
- prove ownership of somebody else's endpoint
- expose browser-based provider admission
- enable the paid reference fixture in production
- send funds

The next real-provider step requires actual counterparty evidence and a real capability adapter. Until those exist, the production paid-provider gate remains closed.
