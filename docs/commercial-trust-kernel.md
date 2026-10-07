# AgentPay Commercial Trust Kernel v0.1

Status: design + executable reference kernel

This document defines the first commercial-trust layer above the existing AgentPay governed payment flow.

The objective is not to give autonomous software broad financial authority. The objective is to make a narrowly stated commercial intent machine-executable while keeping money, identity, data, credentials, compute, provider choice, expiry and evidence inside one explicit authority boundary.

## 1. Core invariant

A commercial action is valid only when all of the following are bound together:

1. **Intent** — the principal's purpose and desired outcome.
2. **Authority** — what may be spent, disclosed, delegated, retained and executed.
3. **Capability offer** — what a provider proposes to do and what it requires.
4. **Selection evidence** — why the chosen offer was permitted and why alternatives were rejected.
5. **Execution authority** — the exact one-shot action handed to the existing AgentPay execution path.
6. **Independent observation** — evidence of what actually happened.
7. **Outcome assessment** — whether the stated commercial outcome was satisfied.
8. **Commercial proof** — portable binding of the above evidence.

No planner, model, browser or provider is allowed to manufacture authority that is absent from the Commercial Intent Capsule.

## 2. Commercial Intent Capsule

The capsule is the user's durable statement of delegated commercial authority.

It currently binds:

- principal
- purpose
- desired outcome
- maximum spend
- settlement asset
- allowed capabilities
- allowed disclosures
- prohibited disclosures
- minimum evidence
- minimum expected confidence
- maximum credential lifetime
- maximum compute
- maximum retention
- allowed providers
- allowed jurisdictions
- preference order
- expiry
- whether automatic execution is explicitly authorized

The capsule is immutable and canonically hashed.

A conflict such as allowing and prohibiting the same disclosure fails closed at construction time.

## 3. Capability Offer

A provider does not publish merely an API endpoint. It publishes a machine-readable commercial offer.

An offer binds:

- provider
- capability
- exact price
- settlement asset
- disclosures required
- evidence produced
- expected confidence
- credential lifetime
- compute consumption
- retention period
- latency
- jurisdiction
- expiry

An offer may be cheap and still be commercially invalid because it asks for excessive data, retains information too long, supplies insufficient evidence, exceeds compute/credential limits, is outside the permitted jurisdiction, or does not meet the required outcome confidence.

## 4. Evaluation

Every offer is evaluated independently against every authority dimension.

The result is **PERMIT** or **DENY** with concrete reasons.

Examples:

- `price-exceeds-authority`
- `prohibited-disclosure-required`
- `credential-ttl-exceeds-authority`
- `retention-exceeds-authority`
- `required-evidence-missing`
- `confidence-below-target`
- `jurisdiction-not-authorized`

There is no hidden aggregate trust score that can offset an authority violation.

A provider cannot compensate for prohibited source-code disclosure by being cheaper or faster.

## 5. Pareto frontier

Only permitted offers enter planning.

AgentPay removes commercially dominated offers using these dimensions:

- price — lower is better
- disclosure count — lower is better
- retention — lower is better
- compute use — lower is better
- latency — lower is better
- expected confidence — higher is better

An offer is dominated only when another permitted offer is no worse on every dimension and strictly better on at least one.

This preserves meaningful alternatives instead of collapsing everything into one opaque score.

## 6. Deterministic Companion selection

Companion does not receive sovereign discretion.

The capsule carries an explicit deterministic preference order. The default is privacy-first:

1. disclosure
2. price
3. retention
4. compute
5. latency
6. confidence

The planner chooses only from the Pareto frontier.

Changing the selection preference is itself an authority decision because it changes the principal's economic policy.

Ties are resolved deterministically by provider ID and offer ID.

## 7. Human approval and automatic execution

The planner produces a plan, not an action.

By default:

`requires_human_approval = true`

Automatic execution becomes possible only when the capsule explicitly contains:

`automatic_execution = true`

That flag still does not relax any other authority dimension.

The next implementation layer will additionally bind automatic execution to a specific action class, cumulative budget and revocation state before dispatch.

## 8. HIO contract

The human interface should not expose raw policy machinery by default.

The minimum decision surface is:

- goal
- selected capability
- provider
- all-in price
- data disclosed
- retention
- credential lifetime
- compute use
- expected confidence
- evidence returned
- alternatives rejected and why
- whether explicit approval is required

Every displayed value must come from the hashed capsule, offer or plan. HIO must not invent explanatory facts.

A user can drill down to the canonical objects and hashes.

## 9. Commercial Proof

The first proof envelope binds:

- capsule digest
- plan digest
- selected offer ID and digest
- execution authority digest
- underlying AgentPay action proof hash
- observed outcome
- observation time

This deliberately references existing evidence instead of copying mutable data into a second large receipt.

Later versions can add independent signatures and cross-implementation verification without changing the conceptual boundary.

## 10. Required separation of powers

The system must preserve this separation:

**DDC** formulates and tests possible commercial strategies.

**Companion** observes state, discovers capability offers and proposes a plan.

**Frequency** determines whether the proposed action is inside delegated authority.

**Execution Gateway** performs only the exact granted action.

**Independent Observer** reconstructs what actually happened.

**Outcome Evaluator** determines whether the intended result was achieved from evidence.

**HIO** explains the decision and evidence to the human.

No single component may both propose, authorize, execute and self-certify the same commercial action.

## 11. Threat model

The design explicitly handles these initial failure classes:

- browser lowers the advertised price
- provider changes scope after selection
- provider asks for a prohibited disclosure
- provider requests excessive credential lifetime
- provider retains data beyond authority
- provider advertises inadequate evidence
- provider does not meet minimum confidence threshold
- stale offer replay
- expired user authority
- unauthorized jurisdiction/provider
- planner silently chooses a dominated offer
- planner silently changes user preference order
- plan is mutated after approval
- execution proof is substituted
- outcome text is modified after proof creation

The existing AgentPay durable one-shot execution journal continues to handle dispatch uncertainty, replay and in-doubt settlement semantics at the payment boundary.

## 12. Next vertical slice

The next implementation should demonstrate:

> Validate a release to a stated assurance target under a bounded budget.

Candidate offers include:

- a local no-cost capability
- an external provider that requests repository source and is denied
- a privacy-preserving external validator that requires only rendered output
- an expensive provider that is commercially dominated

Companion produces the frontier and selection explanation.

Frequency authorizes only the exact selected commercial action.

The existing Base/USDC flow performs settlement only if required.

The observer binds returned evidence to settlement and execution.

The final Commercial Proof explains the complete economic decision.

That is the first end-to-end reference implementation of the commercial trust protocol.
