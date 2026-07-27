# RFC 1 — Forecast targets and the what-if operator

*Status: draft · Part 1 of 4 · Scope: grammar extension, no new dimensions*
*Depends on RFC 0 (concept model). Per-dimension levers in RFC 2. Build order in RFC 3.*

---

## Motivation

RFC 0 specifies a deviation engine: `entity × metric-per-unit × comparison`. Left at plan / prior period / internal peer, all three comparisons look backwards, with two consequences:

1. **Nothing in the grammar predicts.** A CXO asking "where will this land?" falls outside the model.
2. **Nothing in the grammar answers "what if?"** The product's stated scope — performance analysis *inclusive of* predictive analytics and what-if scenarios — is not expressible in its own concept model.

This part closes both without adding a dimension. Forecast becomes a target source that generalizes the other three; what-if becomes the inverse of the existing grammar.

## Part 1 — Forecast as a target source

### The unification

Prior period and internal peer are not alternatives to a forecast. They *are* forecasts with the model left implicit:

| Target source | Underlying model | Interval | Evidence quality |
| :---- | :---- | :---- | :---- |
| **Plan** | human-supplied prediction | none stated | depends on freshness + granularity match |
| **Forecast** | learned model over the entity's history and drivers | explicit | gated on history length and stability |
| **Prior period** | naive persistence (`ŷ = y₍t−1₎`) | derivable from history variance | available with any history |
| **Internal peer** | cross-sectional central tendency | derivable from sibling spread | available once the entity has siblings |
| **Standard / ceiling** | definitional (routing time, theoretical capacity) | none — it is a definition | typed separately; never confused with plan |

Making this explicit turns the fallback chain from five unrelated behaviours into **one mechanism with five estimators**, each carrying the same three properties: a stated model, an uncertainty interval, and an evidence grade.

### The consequence worth shipping

Once a target has an interval, **deviation becomes testable**. Today every BI tool shows every metric as up or down against something, and nobody can tell which deltas matter.

> The system surfaces a deviation only when it exceeds the target's own uncertainty, and it states which target it used and how confident that target is.

A −4% against a target with a ±9% band is not a finding. A −4% against a ±1% band is. That distinction is the product, and it is the platform's existing honesty register (ready / investigate / blocked) applied to the comparison itself rather than to the data.

### Evidence-ranked resolution

Order of preference, availability-gated:

1. **Plan**, if current and at matching granularity. A stale or wrong-grain plan is a worse target than a naive one and is demoted, not preferred. Plan freshness is typed evidence like any other.
2. **Forecast**, when the history gate clears.
3. **Prior period**, as the persistence fallback.
4. **Internal peer**, offered *alongside* rather than instead of the above, because it answers a different question: is this entity worse, or is the whole class worse?

Where a definitional standard exists (Capacity ceilings, Throughput routing times — see RFC 2), it is shown as a separate typed target rather than competing in this order.

Hard rule: **the system always states which target it used and why the others were not.** Silent fallback is the failure mode of every planning tool on the market.

### Entity birth and death

A forecast, a prior-period comparison and a peer set all assume the entity existed before and has comparable siblings. Assortment churn, supplier onboarding, new lines and new segments break all three. The model must distinguish *deviation* from *absence of history* and say so, rather than reporting a phantom −100%. This is a correctness requirement, not an edge case; it is the most common way predictive features lose user trust in the first week.

## Part 2 — What-if as the inverse operator

### The grammar, run backwards

Forward: `entity × metric-per-unit × target → deviation`

Inverse, two modes:

- **Projection** — perturb a lever, propagate through the recovered model, re-derive the metric. *"If supplier X's lead time improves by three days, what happens to cost-to-serve for segment B, and to days inventory?"*
- **Goal-seek** — fix the metric, solve for the lever. *"What price and mix gets DB2 on product group C back to plan?"*

Same machinery, opposite directions.

### Why allocation is the substrate, not just the provenance story

RFC 0 positions the explicit, versioned allocation rule as the provenance showcase. It is more than that: **an explicit allocation rule is what makes propagation computable.** A simulation can only push a change from a lever through to cost-per-customer if the path from cost to customer is a declared, inspectable rule rather than a hidden aggregation. Every argument for making allocation explicit is doubled here — and the decision for named, plural schemes (RFC 0) is a hard requirement, because a scenario computed under an unnamed scheme is not reproducible.

### Typed levers

Levers are not free-text. A closed set keeps simulation auditable and the UI finite.

| Lever type | Perturbs | Example | Dimensions |
| :---- | :---- | :---- | :---- |
| **Volume** | quantity on an entity | +10% units on product group C | Demand, Offer, Supply |
| **Price** | unit value | −2% list price on segment B | Offer, Supply |
| **Mix** | share across siblings | shift 15% of volume from channel A to B | Demand, Offer, Supply |
| **Rate** | a ratio in the model | scrap rate on line 2 from 4% to 2.5% | Throughput, Supply, Capacity |
| **Timing** | a duration | supplier lead time −3 days; DSO −8 days | Supply, Capital, Throughput |
| **Capacity** | an availability ceiling | one additional shift on line 2 | Capacity |
| **Allocation key** | the rule itself | freight by weight vs. by revenue | all |

The last one is distinctive. No other tool lets a CXO ask *"is this customer unprofitable, or is my allocation rule wrong?"* and get a computed answer.

### Hard rules

- **No path, no simulation.** A lever may only be perturbed against a metric if the recovered model contains a structural path between them. Where none exists the scenario is refused, with the missing link named. This is "non-fit stays dark", one floor up — and the refusal is itself a coverage-map entry and therefore a sales line.
- **Scenarios are pinned artifacts.** Every scenario stores the model version, the allocation scheme, the target source and the lever set. A scenario that cannot be recomputed identically does not exist.
- **Projection is not prophecy.** Simulated results inherit and compound the intervals of their inputs. A projection is displayed with its band or not at all.
- **The company model outranks the prior here too.** Elasticities and propagation coefficients are recovered from the company's own history where evidence supports it. Dimension-level defaults are candidate hypotheses, never substitutes.

## Part 3 — Coverage map extension

Two states join lit / partial / dark, per dimension:

- **Forecastable** — enough clean history at this granularity to fit and validate a model. Gated on history, not on connection.
- **Simulatable** — the structural paths and allocation rules needed to propagate a lever are present.

This sharpens the expansion motor. Each state names its own next step and its own commercial line:

- partial → "connect planning data and the Soll column lights up"
- not yet forecastable → "eighteen more months of history, or connect the archive, and this metric gets a projected target"
- not yet simulatable → "the link between goods receipt and order line is missing; supply it and this dimension becomes a scenario surface"

Same object, three views, two more rungs to sell.

## Open questions

- **Forecast gate.** What minimum history, at what granularity, with what stability test, qualifies a metric as forecastable? Under-gating destroys trust faster than any missing feature does.
- **Backtesting display.** Do we show the forecast's own track record? Argued yes — it belongs in the same honesty register as everything else, and a target that publishes its hit rate is unusual enough to be a differentiator.
- **Interval presentation.** A band is correct and most executives read it as hedging. What is the plain-language form? ("Between X and Y in four of five comparable periods.")
- **Scenario composition.** Do two scenarios compose, and how are interacting levers reconciled? Probably: composition allowed, interaction terms flagged as unmodelled.
- **Ownership.** Is a scenario a workspace artifact (shared, governed, versioned) or a personal sketch? Likely both, with an explicit promotion step.
- **Plan freshness typing.** What evidence establishes that a connected plan is current enough to outrank a forecast?
