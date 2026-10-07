# HIO Visual Surface — AgentPay Proof

AgentPay Proof is the first DDC/Frequency/HIO fixture where an approved visual reference is treated as an immutable interface contract.

## Architecture

The visual surface is separated into three layers:

1. **Approved art layer** — exact crops from the approved 1672 × 940 mockup. The logo, header, navigation rail, hero, workflow river, featured-services panel, activity panel, status panel and footer are independent image assets positioned in the original coordinate system.
2. **Semantic interaction layer** — transparent, keyboard-focusable HTML controls aligned to the approved visual controls. The artwork is not responsible for behavior.
3. **Runtime-truth layer** — live wallet/network/activity values cover only the regions that must change. Static mockup telemetry is never trusted as runtime evidence.

This separation preserves visual fidelity without turning the website into a dead screenshot.

## HIO invariants

- approved geometry remains 1672 × 940
- desktop scales as one centered composition
- no independent section stretching
- no scroll on judge desktop
- visual controls have semantic keyboard-accessible counterparts
- Base and wallet state come from live runtime data
- activity is current-session data only
- no private key enters the browser/server contract
- reduced-motion users do not receive decorative animation
- visual art does not run a continuous canvas loop
- approved visual assets stay below the current 2.5 MB fidelity budget

## Visual Frequency gate

A release is rendered in a real browser at 1672 × 940 and compared to the approved reference with Visual Frequency.

The first layered reconstruction produced:

- candidate: 1672 × 940
- approved reference: 1672 × 940
- visual score: **0.976159**
- threshold: **0.80**
- verdict: **PASS**

The earlier broken half-screen render scored 0.556 and was correctly rejected.

The HIO rule is therefore evidence-based: a structural test suite can pass while the human interface fails. Production promotion requires both behavioral assurance and rendered visual evidence.

## Evolution

This implementation deliberately prioritizes exact reference reconstruction. HIO can later replace individual raster slices with optimized vector/raster assets one section at a time, but each replacement must independently meet or improve the Visual Frequency score and the resource budget before it replaces the approved slice.
