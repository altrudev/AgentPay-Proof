# AgentPay Proof — Judge-Facing GUI Contract

## Purpose

The interface must explain AgentPay Proof without requiring blockchain, agent, or Frequency knowledge. A first-time visitor should understand within ten seconds:

> An AI agent can buy a service, but only inside explicit spending authority. AgentPay Proof independently verifies what was authorized, what was paid, and what was delivered.

The GUI is a product surface over the existing governed workflow. It must never manufacture verification state in the browser.

## Visual direction

A calm assurance/fintech interface: warm off-white canvas, ink/navy typography, restrained cobalt accents, subtle borders and depth, generous spacing, crisp geometric icons. Avoid crypto-neon, terminal aesthetics, dense admin dashboards, gradients used as decoration, and excessive animation.

Typography uses the system font stack so no external font dependency or tracking is required. Layout is responsive and readable at 360px through desktop widths.

## Information hierarchy

### Header
- AgentPay Proof wordmark
- short descriptor: "Governed payments for autonomous agents"
- environment badge: DEMO / TESTNET / LIVE
- no wallet secret or infrastructure controls

### Hero
Headline: "Let agents pay. Keep authority verifiable."

Supporting copy: "AgentPay Proof binds an agent's intent, spending authority, payment, service result and independent observation into one portable proof."

Primary action: Run authorized purchase
Secondary action: Try denied purchase

### Authority envelope
Show before execution:
- maximum spend
- network
- asset
- service
- recipient binding
- expiry behavior

This makes the governing constraint visible before the result.

### Transaction timeline
Seven stages, always in the same order:
1. Request
2. Quote
3. Authority
4. Payment
5. Execution
6. Observation
7. Proof

States: waiting, active, passed, denied, not-verified. Denial stops visibly at Authority. No later stage may appear successful.

### Result
Denied:
- "Purchase blocked before payment"
- reason
- "$0 transferred"
- "No transaction created"

Success:
- "Transaction independently verified"
- amount / asset / network
- settlement reference
- observer
- proof hash
- Download JSON proof
- explorer action only for a genuine on-chain hash

### Explanation
Three short concepts:
- Bounded authority — exact amount/service/recipient/network
- Independent observation — agent claims are not treated as evidence
- Portable proof — intent through outcome is cryptographically bound

## Trust labels

DEMO means controlled fixture settlement. It must never say "verified on-chain".
TESTNET means real test-network settlement observed from RPC.
LIVE means real-value settlement and is disabled unless explicitly configured.

"VERIFIED" means the supplied evidence passes AgentPay Proof verification. "VERIFIED ON-CHAIN" is permitted only when the settlement observer has independently obtained the matching chain transaction/receipt.

## Security boundary

Browser:
- display state
- submit bounded demo request
- download returned proof

Server:
- quote generation
- authority decision
- orchestration
- verification
- proof generation

Private/internal:
- Frequency/Conduit
- wallet/signing authority
- RPC credentials if any
- deployment credentials

No browser endpoint exposes shell, Conduit, Frequency internals, signing secrets, arbitrary RPC forwarding, or filesystem access.

## Demo choreography

Default screen is populated enough to explain the system but has no false successful transaction.

Authorized preset: 0.25 USDC under a 1.00 USDC ceiling.
Denied preset: 2.00 USDC over the same ceiling.

A judge should be able to run both cases in under 90 seconds. The UI updates the timeline from the server response. A tamper demonstration operates on a copy of the proof and must end in NOT VERIFIED.

## Acceptance criteria

- One-screen primary workflow on common laptop viewport.
- Mobile layout remains usable without horizontal scrolling.
- Denied case visibly stops before Payment.
- Demo fixture never presents as on-chain.
- No verification verdict is computed only in JavaScript.
- Proof download contains the exact server-returned proof.
- No secret values in HTML, JS, logs, repo, or API responses.
- Accessibility: semantic controls, keyboard focus, sufficient contrast, reduced-motion support.
- UI/API tests plus final Frequency sweep pass before deployment.
