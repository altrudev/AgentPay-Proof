# Production x402 readiness

Status: **CODE COMPLETE / DEPLOYMENT + RECIPIENT CONTROL PROOF PENDING**

This document describes the fail-closed production path for the AgentPay code-analysis resource.

## Authority chain

The production flow is:

1. public provider identity is served by `agentpay.altru.dev`;
2. Prometheus independently probes provider DNS/TLS, health, identity and discovery;
3. the configured Base recipient signs a short-lived EIP-191 control challenge;
4. the three independent evidence classes are assembled:
   - identity-control;
   - endpoint-control;
   - recipient-control;
5. the provider manifest is signed by the dedicated Ed25519 provider key;
6. the manifest is self-verified and imported into the durable provider registry;
7. only then may `AGENTPAY_ENABLE_X402_CODE_ANALYSIS=1` expose a payment challenge;
8. client payment authority is locally and independently verified against Base;
9. the exact `transferWithAuthorization` call is simulated with `eth_call`;
10. the resource executes once and its result is durably bound;
11. xpay submits settlement;
12. AgentPay independently reconstructs the Base transaction, AuthorizationUsed event and Transfer event;
13. lost facilitator responses are reconcile-only by exact payer + EIP-3009 nonce and never cause a second resource execution or blind re-settlement.

## Facilitator

The admitted production settlement candidate is the public xpay x402 facilitator:

- `https://facilitator.xpay.sh`
- x402 v2
- `exact`
- Base mainnet `eip155:8453`
- native Base USDC
- public/no API credential
- gas-sponsored settlement

AgentPay does not delegate payment verification authority to xpay. The production resource requires local EIP-712 recovery, chain check, USDC contract code, balance, authorization-state check and exact `eth_call` simulation before resource execution.

The facilitator is then used only to submit settlement. Its returned transaction is not trusted as proof of payment; the Base RPC reconstruction is authoritative for final AgentPay evidence.

## Provider identity

Provider ID:

`provider:altru-agentpay`

Operator identity:

`Valentyn Rukhaylo / Altru.dev (individual operator)`

Brand/project:

`Altru.dev / AgentPay`

Provider domain:

`agentpay.altru.dev`

Paid adapter:

`https://agentpay.altru.dev/api/x402/code-analysis`

Base recipient:

`0xebd095378327f025e7d5852868cb7366627aadfc`

No incorporation is implied by the provider identity string.

## Provider manifest key

The provider manifest uses a dedicated Ed25519 key. The private key remains outside the repository and is required to have owner-only file permissions. The public key is pinned in `src/provider_profile.py`.

The VPS does not need the private signing key. Prometheus can create the signed portable manifest, and the VPS verifies/imports it using only the pinned public key.

## Onboarding CLI

Create a short-lived recipient-control challenge:

```bash
PYTHONPATH=. python3 scripts/provider_onboarding.py challenge --out provider-challenge.json
```

The exact `message` field is signed by the configured recipient wallet using EIP-191/personal-sign. It explicitly states that the signature proves recipient control only and is not a payment authorization.

Build the signed provider manifest on Prometheus after the live identity endpoint is deployed:

```bash
PYTHONPATH=. python3 scripts/provider_onboarding.py build \
  --challenge provider-challenge.json \
  --signature-file recipient-signature.txt \
  --signing-key ~/.agentpay-secrets/provider-manifest-ed25519.pem \
  --version 1 \
  --out agentpay-provider-manifest.json
```

The build step independently probes the live provider endpoint before signing.

Import on the VPS:

```bash
PYTHONPATH=. python3 scripts/provider_onboarding.py admit \
  --manifest agentpay-provider-manifest.json \
  --registry /var/lib/agentpay-proof/providers.sqlite3
```

## Public-route gate

The route remains disabled unless all of the following are true:

- live configuration is valid;
- the durable provider manifest loads and re-verifies;
- provider admission is active and unexpired;
- xpay live transport/capability admission succeeds;
- the explicit environment gate is enabled:
  `AGENTPAY_ENABLE_X402_CODE_ANALYSIS=1`.

Without all five, the service fails closed and does not advertise payment authority.

## Current external blockers

At the time of the Frequency sweep:

- canonical repository code is testable on Prometheus;
- xpay live runtime admission passes;
- the dedicated provider-manifest key exists and its derived public key matches the pinned public key;
- `https://agentpay.altru.dev/api/health` is live;
- `https://agentpay.altru.dev/api/discovery?service_id=code-analysis-v1` is live;
- `https://agentpay.altru.dev/api/provider/identity` is still 404 because the updated service has not yet been deployed;
- the VPS remote relay is offline;
- no recipient-control wallet signature has been supplied.

Therefore no provider manifest has been admitted, no public x402 challenge is enabled, and no funds can move through this new resource path yet.
