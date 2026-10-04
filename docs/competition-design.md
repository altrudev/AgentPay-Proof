# AgentPay Proof — Competition Design Contract

Status: design baseline for implementation
Target: Colosseum Crypto World's Fair
Product boundary: AgentPay Proof is hackathon code. Frequency is pre-existing assurance infrastructure and is consumed only through an explicit adapter/evidence boundary.

## Product claim

AgentPay Proof is a governed payment layer for autonomous agents. Blockchain settlement proves that money moved. AgentPay Proof proves that a specific agent payment was within a bounded authority and binds that authorized settlement to an independently observed service outcome.

The product must not claim more than its evidence proves.

## Competition-critical vertical slice

The judge-facing demo MUST make one complete transaction understandable without reading source code.

### Case A — denied before payment

1. A service publishes a machine-readable quote.
2. Agent requests purchase authority.
3. Quote exceeds the spending envelope or violates recipient/service binding.
4. Decision is DENY.
5. No transaction is created or broadcast.
6. Proof records the denial and the exact failed constraint.

### Case B — authorized and verified

1. A service publishes a machine-readable quote.
2. Agent requests authority for that exact quote.
3. Policy returns PERMIT for a bounded amount, asset, chain, recipient, service and expiry.
4. Settlement adapter pays USDC on Base only after validating the permit.
5. Service executes against the bound request.
6. Independent observer evaluates the result separately from the purchasing agent.
7. A portable proof binds intent -> quote -> authority -> settlement -> result -> observation.
8. Verifier recomputes bindings and reports VERIFIED or NOT VERIFIED.

## Required evidence domains

### Intent
- intent_id
- agent_id
- service_id
- request_digest
- created_at

### Quote
- quote_id
- service_id
- recipient
- chain_id
- asset_contract
- amount_atomic
- expiry
- request_digest
- quote_digest/signature when available

### Authority
- decision_id
- decision: PERMIT or DENY
- intent_id
- quote_id
- maximum_amount_atomic
- exact recipient
- exact service
- exact chain_id
- exact asset_contract
- expiry
- policy/evidence reference
- decision digest

### Settlement
- chain_id
- transaction_hash
- sender
- recipient
- asset_contract
- amount_atomic
- block number/hash or finalized status
- quote_id/intent binding carried by local evidence

### Result
- service_id
- request_digest
- result_digest
- completion status

### Independent observation
- observer_id
- observed settlement digest
- observed result digest
- verdict
- observation timestamp
- observer signature/digest

### Proof
- schema/version
- proof_id
- all domain digests
- final proof hash
- verifier result

## Invariants

1. DENY can never reach settlement submission.
2. A permit is unusable for a different recipient, service, chain, asset, amount, quote or expired time window.
3. Settlement amount must be <= the authorized amount and match the accepted quote.
4. Settlement evidence is obtained independently from the agent's narrative.
5. Service result is cryptographically bound to the original request.
6. Observer evidence is distinct from the purchasing agent's claim.
7. Any mutation to a bound evidence domain causes verifier failure.
8. Missing evidence is NOT VERIFIED, never silently treated as success.
9. Secrets/private keys never enter receipts, logs, repository history or browser payloads.
10. Mainnet spending is not required for development; real-value execution requires explicit operator approval.

## Threat model for the hackathon product

The implementation and tests must cover:
- agent attempts to exceed budget
- recipient substitution
- service substitution
- asset/chain substitution
- amount substitution after authorization
- stale/expired quote or permit
- fabricated transaction hash
- mismatched on-chain transfer
- fabricated service result
- result tampering after observation
- self-attestation presented as independent observation
- replay of an already-consumed authority
- incomplete evidence

## UX contract

One screen should show a transaction timeline:

REQUEST -> QUOTE -> AUTHORITY -> PAYMENT -> EXECUTION -> OBSERVATION -> PROOF

A denied run stops visibly at AUTHORITY and shows why.

A successful run shows:
- amount and USDC
- Base network
- authority constraints
- real transaction hash with explorer link
- independent observation state
- VERIFIED / NOT VERIFIED
- downloadable JSON proof

The UI must clearly distinguish DEMO/SIMULATED settlement from real Base settlement. A simulated transaction must never render as VERIFIED ON-CHAIN.

## Implementation phases

P0 — evidence model and verifier
- replace free-form dict evidence with versioned typed schemas
- deterministic canonicalization
- verification routine
- tamper/replay/constraint tests

P1 — quote + service
- deterministic demo paid service
- machine-readable quote
- request/result digest binding

P2 — Base adapter
- Base test environment first
- USDC-compatible ERC-20 transfer path
- receipt/log verification from an RPC provider
- no key material committed
- explicit switch between simulated and on-chain modes

P3 — independent observer
- separate observer component/process
- independently fetch settlement evidence and inspect service result
- emit signed/digested observation

P4 — judge-facing web demo
- one-screen transaction timeline
- denial and success presets
- proof viewer/download
- explorer link

P5 — validation and submission
- external developer trials/reactions
- reproducible setup
- threat model and architecture diagram
- 2–2.5 minute live demo video
- submission copy limited to implemented claims

## Acceptance gate

Competition-ready requires all of:
- real Base USDC-compatible transaction demonstrated
- DENY path proves zero settlement
- successful path independently observes settlement and result
- portable proof verifies from raw evidence
- tampering causes NOT VERIFIED
- replay is rejected
- no secrets in repository or proof
- clean setup from documented instructions
- Frequency/DDC sweep PASS on final commit
- judge can understand the value proposition and complete demo in under three minutes
