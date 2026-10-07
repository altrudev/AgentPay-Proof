# Coinbase CDP x402 facilitator candidate

Status: **OBSERVED CANDIDATE / NOT ADMITTED / NO LIVE PAYMENT AUTHORITY**

This record is deliberately weaker than a FacilitatorAdmission.

## Candidate

- facilitator id: `facilitator:coinbase-cdp-x402-v2`
- operator surface: Coinbase Developer Platform
- host: `api.cdp.coinbase.com`
- verify endpoint: `https://api.cdp.coinbase.com/platform/v2/x402/verify`
- settle endpoint: `https://api.cdp.coinbase.com/platform/v2/x402/settle`
- target rail: x402 v2 exact / EIP-3009
- target network: Base mainnet, `eip155:8453`
- target asset: Base USDC, `0x833589fcd6edb6e08f4c7c32d4f71b54bda02913`

Coinbase documentation describes authenticated x402 verification at the production CDP host and examples using Base mainnet. The x402 specification requires `/verify` to be read-only and distinguishes it from the state-committing `/settle` boundary.

## Independent public transport observation

Frequency probe observer:

`frequency:prometheus-independent-probe`

Probe evidence digest:

`22994553dfb4e8310a4a04a2a3a8356044f51268df87fc531ed17fc4d714f6e3`

Observed public transport properties:

- DNS host: `api.cdp.coinbase.com`
- unauthenticated `POST /platform/v2/x402/verify`: HTTP 401
- unauthenticated `POST /platform/v2/x402/settle`: HTTP 401
- TLS certificate subject: `CN=coinbase.com`
- TLS issuer: `CN=WE1,O=Google Trust Services,C=US`
- observed TLS SPKI SHA-256: `sha256:3629e1923cd6465df7c6621eec65e2931e3da959add4a868c85dcf4f3e3f20ca`
- observed certificate SHA-256: `sha256:8723474657b0a08ca487d45f02a9f7ccfea50f8863a6f5c1c55a4bf61f5668ae`

The DNS addresses are retained in the timestamped evidence artifact. They are observations, not permanent authority pins.

## What this proves

The independent probe proves only that, at the observation time:

1. the documented host resolved;
2. its TLS chain validated under the system trust store;
3. the observed leaf public key produced the recorded SPKI digest;
4. the documented verify and settle paths existed;
5. both paths rejected an unauthenticated synthetic request before any valid payment material was supplied.

## What this does not prove

This does **not** prove:

- the legal counterparty identity required for production admission;
- authenticated support for our exact Base-mainnet EIP-3009 profile;
- that authenticated `/verify` is read-only in the operational deployment;
- that authenticated `/settle` is the only state-committing boundary;
- CDP credential scope, revocation, rate-limit or incident behavior;
- a safe certificate/SPKI rotation policy;
- that a real provider has been independently admitted;
- that any wallet should sign or any payment should be requested.

## Remaining admission blockers

A production admission remains fail-closed until all are independently evidenced:

1. legal/counterparty identity and terms;
2. least-privilege CDP credential configuration;
3. authenticated supported-scope observation for `exact` + `eip155:8453` + Base USDC;
4. authenticated invalid-payment probe showing `/verify` performs no settlement or nonce consumption;
5. controlled settlement test using explicitly bounded test value/authority and independent Base reconstruction;
6. certificate/SPKI rotation handling that does not require silently trusting an unexpected key;
7. explicit FacilitatorBinding + FacilitatorTransportProof minted from the evidence;
8. separately admitted real provider and resource;
9. final DDC/Frequency review before public API exposure.

No credentials, wallet signatures, real payment payloads or funds were used to create this candidate record.
