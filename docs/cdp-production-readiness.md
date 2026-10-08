# CDP production readiness

Status: **fail-closed; transport and resource quote observed; authenticated capability proof pending**

This document defines the final production gate for the Coinbase Developer Platform x402 facilitator profile and the real CDP SQL x402 canary resource.

## Implemented

- canonical facilitator transport probe evidence
- reviewed TLS SPKI pin
- exact no-redirect runtime adapter
- TLS identity check before bearer-token release
- request-bound short-lived CDP JWT generation
- Ed25519 and ES256 CDP API-key support
- exact full-path JWT binding
- authenticated `GET /supported` capability evidence model
- facilitator admission requires authenticated scheme/network capability evidence
- live x402 resource quote probe that never signs or pays
- canonical live SQL canary quote evidence
- fail-closed readiness command

Run:

```bash
python3 scripts/cdp_readiness.py
```

A non-zero exit is expected until every production blocker is resolved.

## Current independently observed facts

### Facilitator transport

Reviewed production host:

`api.cdp.coinbase.com`

Reviewed production x402 base:

`https://api.cdp.coinbase.com/platform/v2/x402`

Reviewed TLS SPKI SHA-256:

`sha256:3629e1923cd6465df7c6621eec65e2931e3da959add4a868c85dcf4f3e3f20ca`

Both unauthenticated `/verify` and `/settle` returned HTTP 401 during the independent probe.

### Real x402 canary

Resource:

`https://x402.cdp.coinbase.com/platform/v2/data/query/run`

Observed quote:

- x402 version: 2
- scheme: `exact`
- network: `eip155:8453`
- asset: Base USDC `0x833589fCD6eDb6E08f4c7c32D4f71b54bdA02913`
- amount: `100000` atomic units = US$0.10
- payTo: `0x631e240FE781083A5571552cE82036d96B158696`
- timeout: 60 seconds
- token domain: `USD Coin`, version `2`

The quote was obtained without a payment signature. No funds moved.

## CDP credential boundary

The runtime consumes:

- `CDP_API_KEY_ID`
- `CDP_API_KEY_SECRET`

The secret is never written to the repository or evidence files. It is held only by the request-bound token provider.

Each bearer JWT is bound to:

- exact HTTP method
- `api.cdp.coinbase.com`
- exact full path such as `/platform/v2/x402/supported`
- maximum 120-second lifetime
- unique nonce

The runtime verifies the reviewed TLS SPKI before invoking the token provider.

Redirects are rejected.

## Certificate rotation

Certificate/SPKI changes are **not** trusted automatically.

A changed SPKI produces:

`facilitator-runtime-spki-mismatch`

The rotation procedure is:

1. run a new independent transport probe;
2. retain the evidence artifact;
3. verify the new certificate chain, hostname and endpoint behavior;
4. review why the SPKI changed;
5. update the reviewed profile in a dedicated PR;
6. rerun the full test/readiness gate;
7. only then permit credentials to be released to the new TLS identity.

This favors a short fail-closed outage over silently trusting an unexpected key.

## Remaining production blockers

### 1. Authenticated capability proof

The CDP key must call:

`GET /platform/v2/x402/supported`

The canonical response must independently prove x402 v2 `exact` support on `eip155:8453`.

Until that evidence exists, a production FacilitatorAdmission cannot be minted.

### 2. Authenticated verify semantics

A bounded invalid-payment test must show that authenticated `/verify` rejects invalid authorization without consuming the authorization nonce or producing a settlement transaction.

### 3. Real provider admission

The paid resource still needs the provider-assurance contract required by AgentPay:

- provider identity/control evidence
- endpoint-control evidence
- exact recipient-control evidence
- signed Provider Manifest
- durable Provider Admission

The observed 402 quote alone is not treated as proof of recipient ownership.

### 4. Controlled settlement

The final canary requires an explicitly approved wallet signature and US$0.10 Base-USDC authorization.

The controlled transaction must then prove:

`wallet approval -> /verify -> resource execution -> /settle -> independent Base transaction reconstruction -> durable verified receipt`

AgentPay does not sign or spend autonomously at this gate.

## Claim ceiling

The system is production-path complete in code but **not production-authorized** until the blockers above are resolved with external evidence.

No documentation, successful unit test, or public endpoint observation may be substituted for those authority boundaries.
