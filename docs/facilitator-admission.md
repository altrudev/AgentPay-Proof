# Facilitator admission and transport assurance

The x402 facilitator is a commercial infrastructure counterparty, not a trusted helper object.

This boundary adds three separately hashed objects:

- **FacilitatorBinding** — legal identity, exact /verify and /settle HTTPS endpoints, admitted payment schemes, networks and assets, DNS names, TLS SPKI pins, validity window and monotonic version.
- **FacilitatorTransportProof** — independently observed endpoint identity, resolved hostname, TLS SPKI identity, proof validity, and evidence that /verify is verification-only while /settle is settlement-only.
- **FacilitatorAdmission** — the decision binding the exact facilitator configuration to the exact transport proof.

Admission fails closed on endpoint substitution, DNS substitution, TLS identity substitution, missing independent observation, unsupported payment scope, role confusion between /verify and /settle, expiry, or revocation.

The runtime adapter is also checked against the admitted facilitator ID, verify URL, settle URL and observed TLS SPKI identity before payment authorization proceeds. This prevents replacing the admitted transport with a different client object after approval.

The x402 execution approval now binds the facilitator binding digest, transport-proof digest and admission digest. Those exact digests are revalidated before wallet signature release, before /verify and again before /settle.

No real facilitator is admitted by this change. No x402 route is exposed through the public API. The reference facilitator used in tests is synthetic and has no production authority.

A future live facilitator must therefore satisfy all of the following before the first truthful commercial transaction:

1. independent identity and legal-counterparty review;
2. exact endpoint and supported-network admission;
3. independent DNS/TLS transport observation;
4. independent behavioral confirmation that /verify does not settle and /settle is the settlement boundary;
5. production adapter enforcement of the same endpoint and TLS identity;
6. explicit admission with a bounded validity window;
7. successful provider admission for the paid resource;
8. the existing x402 verify → resource → settle → independent Base reconstruction chain.

The claim ceiling remains narrow: transport admission proves the endpoint identity and observed behavior represented by the bound proof. It does not claim the facilitator cannot later be compromised, so expiry, revocation, runtime rebinding checks and independent on-chain reconstruction remain mandatory.
