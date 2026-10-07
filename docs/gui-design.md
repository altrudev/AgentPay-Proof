# AgentPay Proof — Approved Judge-Facing GUI Contract

## Authority

This document is subordinate to the approved AgentPay Proof homepage mockup. The mockup is the visual source of truth. Implementation changes must preserve its composition rather than reinterpret it.

The approved surface is a single-screen 1672 × 941 design space that scales as one unit to the available viewport. No scrolling is permitted on the primary desktop view. The implementation may change runtime values and interaction state, but not the approved visual hierarchy.

## Approved composition

### Top bar

Left:
- approved AgentPay Proof lockup
- subtitle: `AUTHORIZED • PAID • EXECUTED • VERIFIED`

Center:
- `AGENT COMMERCE // INDEPENDENT VERIFICATION // OPEN STANDARDS`

Right:
- Base network selector
- search icon
- theme icon
- menu icon

No additional permanent wallet button may be inserted into the approved header. Wallet connection is reached through the Base selector and the primary service action so the approved composition does not drift.

### Left navigation

Exactly seven entries:
1. Home
2. Explore
3. Run Service
4. Proofs
5. Developers
6. Docs
7. GitHub

Home is highlighted by the blue rail treatment.

Lower-left attribution:
- `BUILT / GLOBALLY / ROOTED / INTEGRITY`
- `Val Rukhaylo`
- `Altru.dev`
- `Powered by Frequency assurance`

### Hero

Exact headline:
`LET AGENTS PAY.`
`KEEP AUTHORITY`
`VERIFIABLE.`

Exact supporting copy:
`Autonomous agent commerce with real payments, governed boundaries, and independently verifiable proof.`

Actions:
- `Run a Service →`
- `Explore Services →`

Right-side statement:
- REAL PAYMENTS
- CLEAR BOUNDARIES
- INDEPENDENT OBSERVATION
- VERIFIABLE PROOF
- A MORE OPEN
- MACHINE ECONOMY

### Living evidence landscape

The background is not decorative wallpaper. It represents intent becoming independently verifiable economic evidence.

Required visual structure:
- dark navy/black environment
- illuminated mountain/data terrain
- dominant blue/white flowing evidence river
- Ukrainian vyshyvanka geometry used as a structural vertical bridge, not as a logo or trident
- glass evidence objects on the right
- dense data particles, depth and directional motion
- `FROM INTENT / TO VERIFIED PROOF` at the right edge

The result must remain technological, sharp and atmospheric rather than cartoony, glossy or generic crypto-neon.

### Seven-stage flow

Always in this order:
1. Intent — Agent requests a service
2. Quote — Get price and allowed scope
3. Authority — Verify policy and limits
4. Settlement — USDC transaction on Base
5. Execution — Service runs in boundary
6. Observation — Independent verification
7. Proof — Get verifiable evidence

The seven glass stage cards sit directly on the evidence river and are part of the landscape, not a separate admin widget.

### Lower dashboard

Three integrated panels:

Featured Services:
- Code Analysis — AI / Security
- Data Research — Analysis / Data
- 3D Generation — Creative / 3D

Live Activity:
- five-row table geometry
- values must come from the current session or remain visibly empty; never invent completed payments

Network Status:
- Base network state
- current block
- gas price
- RPC latency
- wallet state

Live network values must be obtained from the configured RPC. Static fake block, gas, latency or uptime values are prohibited.

### Footer

Left:
`© 2026 Altru.dev · AgentPay Proof · Powered by Frequency assurance`

Right:
`Status    Documentation    GitHub    ↗`

## Interaction boundary

The approved homepage must remain visually unchanged when wallet support is added.

- Clicking the Base network selector may connect/show wallet state.
- `Run a Service` enters the governed live flow.
- If no injected wallet exists, show a modal; do not fail silently.
- Wallet approval remains explicit.
- No private key enters AgentPay Proof.
- Demo mode must not masquerade as real settlement.
- Browser-side controls cannot manufacture VERIFIED state.

## Responsive rule

Desktop and judge presentation use the authoritative 1672 × 941 coordinate system and scale the whole composition proportionally to fit the viewport.

Do not independently reflow or stretch desktop sections because doing so changes the approved design.

Mobile may use a separate compact presentation, but it must preserve the same visual language and evidence order.

## DDC/Frequency visual invariants

A release fails visual QA if any of the following occur:

- a permanent control is added that is absent from the approved mockup
- hero copy, navigation order, seven-stage order or footer identity changes
- page becomes scrollable on the judge desktop surface
- vyshyvanka bridge is removed or replaced with a trident
- evidence river is reduced to a decorative line
- lower panels are detached from the living landscape
- fake network/activity telemetry appears
- DEMO and LIVE states are visually conflated
- wallet errors fail silently
- viewport-specific CSS stretches the composition away from approved proportions

## Acceptance gate

Competition-facing GUI PASS requires:
- approved one-screen composition preserved
- live controls functional without visual drift
- real network values used where shown
- no false activity
- no secrets
- keyboard-accessible semantic controls
- reduced-motion handling
- full unit suite PASS
- JavaScript syntax PASS
- runtime smoke test PASS
- final visual comparison against the approved mockup before production promotion
