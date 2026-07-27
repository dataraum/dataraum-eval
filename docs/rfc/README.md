# Performance dimensions — RFC set

Golden copies, grounded against the three repos and the live ticket set on 2026-07-27
(`dataraum-eval` @ `ee43f0f`, `vendor/dataraum-context` @ `bce2256ab`,
`vendor/dataraum-testdata` @ `a7c57ad`).

| Doc | Owns |
| :---- | :---- |
| [`rfc_0_concept_model.md`](rfc_0_concept_model.md) | the six dimensions, the unit-economics grammar, the coverage map, allocation — and how a **facet** keeps the vocabulary narrow while enabling inference *between* dimensions |
| [`rfc_1_forecast_simulation.md`](rfc_1_forecast_simulation.md) | the target operator, forecast as one estimator among five, what-if as the inverse — with the measured `tfm/` evidence and the **two error terms** a band must cover |
| [`rfc_2_dimension_specs.md`](rfc_2_dimension_specs.md) | per-dimension reference: entities, ladders, unit metrics, levers — plus *can we generate it* / *can we demo it*, and why the generator is a design surface |
| [`rfc_3_sequencing.md`](rfc_3_sequencing.md) | **the document to read if you read one** — two concurrent lanes, exit criteria, ticket mapping, and what a prospect sees at each step |
| [`rfc_4_demo_and_reference_data.md`](rfc_4_demo_and_reference_data.md) | the four jobs of "demo", the partner rights ladder, and the reference company |
| [`rfc_5_evaluation.md`](rfc_5_evaluation.md) | detector calibration vs functional system tests vs model evaluation; the gates per step; comparability across runs / datasets / verticals |
| [`rfc_6_product_surfaces.md`](rfc_6_product_surfaces.md) | where the dimensions actually land: recipes and the staging hub, `frame` induction, the answer agent, drill, teach, reports |
| [`rfc_verification.md`](rfc_verification.md) | the audit behind every edit — claim → verdict → evidence, including this pass's own retractions |

`_source/` holds the original drafts unchanged, including the `_1` variants. RFC 2 merged
them (the `_1` data-availability revision is the base); RFC 3 was re-sequenced rather than
merged.

## The shape of the answer

**The move to performance analytics is already scheduled** — it is Phase 4 of the locked
stabilisation program (DAT-855), whose three strands are this RFC set: answer agent →
root-causing, frame induction acquiring metrics, and "defining a vertical as an ontology
graph". Nothing here waits for permission or for a new slot.

**And it runs in two concurrent lanes.** Lane A is entirely ours — the operating-model
generator, the dimension prior library, the pipeline-error measurement, comparability — and
starts now with no engine dependency. Lane B rides the program. The correctness gates bind
*claims* ("this deviation is significant", "this dimension is lit"), never the build.

## What changed from the drafts

1. **A dimension is a facet, not a vertical** — one vertical per workspace is enforced in
   code, and six verticals would make the cross-dimension queries inexpressible. The facet
   *classifies* the customer's framed model rather than enlarging it, so narrowness holds;
   inference between facets runs on concept edges, verified topology and conformed
   dimensions — never on name similarity.
2. **The priors' home is `frame` induction** — which today seeds from the nearest shipped
   vertical and is known to leak finance vocabulary into other domains. The six dimensions
   are vertical-neutral by construction: they are exactly the seed library that leak proves
   is missing.
3. **The generator is a lever, not a constraint.** It is ours, it is cheap, and it already
   produces exact same-seed counterfactuals for what-if. Five of six dimensions can't be
   graded today; that column is closed by our own sprint, not by a download.
4. **The grammar is the real blocker** — `entity × metric-per-unit × comparison`: extracts
   carry no predicate, and the comparison term does not exist at all.
5. **Prediction is not the long pole.** `tfm/` has measured, calibrated forecasting, a
   passed in-support what-if gate, and a killed scenario-generation app. It is waiting on a
   metric worth forecasting.
6. **Targets before forecasts** — prior-period and peer are SQL; forecast is a runtime. The
   product line is the operator's disclosure.
7. **Measure the pipeline error before claiming deviation significance** — bands must cover
   `pipeline error + model error`; the model term is decided, the pipeline term is DAT-687
   and unstarted.
8. **The reference company is generated into a borrowed schema**, not stitched from wild
   rows — a stitch has no answer key, so it can never be a fixture.

## Decisions taken 2026-07-27 (after the golden pass; evidence in `rfc_verification.md` §second pass)

1. **DAT-687 green-lit** ("ok") — the pipeline-error measurement starts; the July-21 hold
   is released. Lane A order: A4 (DAT-862 remainder) → A3 (DAT-687) → A1/A2.
2. **A1 = the existing corpus extended in place** ("yes, also my understanding") — reference
   company v0 is the finance corpus grown a customer → order → order line → AR invoice →
   receipt chain: DAT-884. Priors thin-sliced to Demand/Offer/Capital: DAT-885.
3. **Forecast is out of the near-term roadmap** ("yes, forecast is out") — DAT-750/751 +
   backtest harness parked; the operator ships with the SQL estimators; `tfm/` remains the
   standing gate. What-if unchanged (allocation stays its hard predecessor).
4. **No run-per-dimension** — the facet coordinate gives per-dimension reads; incremental
   adoption economy belongs to the cache lane (DAT-861); recorded as a design paragraph for
   the DAT-855 strand-3 /refine (RFC 3 open questions).
