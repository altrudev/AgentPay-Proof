# AgentPay Proof — Approved V6 Asset Pack

Source authority:
- the single user-approved AgentPay Proof mockup supplied in-chat
- 1672 × 940 reference surface
- no earlier mockup, broken render, or generated contact sheet is a valid source

DDC/Frequency/HIO reconstruction rule:
- preserve the approved composition and visual language
- separate atmospheric art, geometric identity, proof depth, workflow icons, and service art into independent layers
- keep all text, navigation, wallet state, network state, activity, and proof state semantic/runtime-driven
- every desktop render scales from the same 1672 × 940 coordinate system
- no independently responsive desktop section may drift away from its approved anchor
- no continuous canvas renderer

## Production assets

### Brand
- agentpay-logo.svg
  - vector reconstruction from the exact approved logo region

### Hero atmosphere
- hero-background.webp
  - clean reconstructed top landscape plate
  - no UI text/buttons/stage cards/proof fan
  - 2948 × 618 production WebP

### Workflow atmosphere
- flow-background.webp
  - clean reconstructed braided evidence-river plate
  - no stage cards or labels
  - 2948 × 406 production WebP

### Identity/depth
- vyshyvanka-bridge-exact.webp
  - exact isolated bridge pixels from the approved reference, subject-masked and losslessly preserved before WebP compression
  - transparent background
- proof-card-fan.svg
  - crisp transparent vector reconstruction of the approved proof/evidence card fan geometry
  - no baked background

### Workflow icons
- icon-intent.svg
- icon-quote.svg
- icon-authority.svg
- icon-settlement.svg
- icon-execution.svg
- icon-observation.svg
- icon-proof.svg

Each icon is vectorized from its corresponding approved stage card.

### Service artwork
- service-code-analysis.webp
- service-data-research.webp
- service-3d-generation.webp

These are regenerated from the exact approved service-art regions, with text and panel chrome removed.

## Resource budget

Production raster assets are resized to approximately 2× their display size and WebP-compressed.
Current production WebP pack: under 700 KB total.

## Release gate

A release may not claim visual fidelity until:
1. the live page is rendered at 1672 × 940 in a real browser;
2. Visual Frequency compares that render against the exact approved reference;
3. geometry, coverage, and perceptual similarity all pass;
4. human review confirms no visual drift or asset mismatch.
