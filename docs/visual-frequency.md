# Visual Frequency

Visual Frequency is the first implementation of a visual evidence gate for DDC/Frequency.

The problem it addresses is simple: structural tests can all pass while the rendered interface is visibly wrong. A CSS string, DOM assertion, or unit test cannot prove that a judge-facing page still matches the approved design.

## Evidence model

Visual releases use three distinct evidence objects:

1. **Reference** — the immutable approved mockup.
2. **Candidate** — a screenshot of the actual rendered application at the target viewport.
3. **Diff** — a machine-generated visualization and metric report describing the drift.

The reference for AgentPay Proof is pinned in `docs/approved-mockup.md`.

## Gate

Run:

```bash
python scripts/visual_frequency.py APPROVED.png CANDIDATE.png \
  --threshold 0.80 \
  --diff artifacts/visual-diff.png \
  --json
```

The command exits non-zero on failure.

It evaluates multiple independent signals:

- coarse visual similarity
- medium-resolution visual similarity
- edge/geometry similarity
- active-content coverage
- aspect-ratio agreement

Coverage is especially important because it catches catastrophic failures such as a correctly styled interface rendering at half width with a large blank region.

The score is deliberately not a claim of artistic correctness. It is an automated regression gate. Human approval remains the authority when visual changes are intentional.

## DDC/Frequency workflow

The correct build loop is:

```
approved reference
    ↓
asset decomposition
    ↓
HTML/CSS implementation
    ↓
real browser render
    ↓
screenshot
    ↓
Visual Frequency comparison
    ↓
FAIL → repair → render again
PASS → human review
    ↓
deploy
```

A release must not be described as matching the mockup unless the rendered candidate has actually been compared with the approved reference.

## AgentPay target

Desktop judge surface:

- 1672 × 940 reference coordinate space
- proportional fit into the real browser viewport
- no scrolling
- no clipping
- no blank unused viewport caused by scaling logic
- all runtime values remain truthful

Mobile is a separate presentation and should use its own approved reference rather than being compared against the desktop image.

## Future Frequency integration

The generic capability should eventually live in Frequency rather than AgentPay:

- screenshot capture adapter
- reference registry
- visual evidence receipts
- per-region thresholds
- typography/layout/object masks
- regression history
- approved intentional-diff workflow
- automatic rollback or release denial on visual regression

AgentPay Proof is the first production fixture.
