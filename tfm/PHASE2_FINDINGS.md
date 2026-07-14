# Phase 2 findings — simulate ground gate (DAT-744, 2026-07-14)

The gate for the settled simulate application list (DAT-741 restructure).
Probes: `tfm/phase2/`; results rows: `tfm/output/phase1/*.jsonl`
(`p5_intervention`, `p5_generate_fidelity`). Corpora:
`tfm/phase2/generate_lever_corpora.py`.

## The lever (testdata d7a6b94)

`Lever(period_k, factor, type="price_level")` — a **DGP intervention**, not a
post-hoc injector: sale amounts from month `period_k` scale by `factor`,
propagating naturally through the cascade (AR → receipts → cash/bank →
TB/BS). Scaling happens after all RNG draws and no control flow branches on
amount values, so the RNG stream is identical with and without the lever:
**a same-seed pair is an exact counterfactual** (proven in
`tests/test_generators.py::test_price_level_lever_is_exact_counterfactual`;
measured in-corpus: revenue ratio == factor post-lever, pre-lever months
byte-identical). `run_scenario(lever=…)` records `intervention.yaml` beside
the data. Grid: factors {0.85…1.20} support, 1.10 held out, {0.50, 1.50}
out-of-support, × seeds {42,43}, 48 months, k=36.

## Part 3 first — generate() fidelity gate: **CUT** (app #3 dead)

Pre-registered fail-once gate for scenario row generation.
`TabICLUnsupervised.generate()` on 2,000 clean journal_lines:

- marginals 13–19× the natural seed-to-seed distance on every money column
  (only cost_center passes);
- **debit/credit mutual exclusivity 0%** (real rows: 100%);
- **ledger identity `net = debit − credit` holds on 9.3%** of generated rows
  (real: 100%).

Value-range-plausible, structurally lawless — useless for cycle-grain
scenarios. CUT per the ground-first rule; gate cost 3.8 s. Apps #1–2 stand.

## P5 Leg A — forecast adaptation to a structural break (in-support)

Recovered effect fraction ((ŷ − y_baseline) / (y_levered − y_baseline),
pooled; 1.0 = fully tracked) after δ levered months visible in context,
mean over factors {0.85, 1.15, 1.20} × seeds:

| engine | δ=1 | δ=2 | δ=6 |
|---|---|---|---|
| TabICL v2 forecaster | 0.61 | 0.34 | **0.69** |
| ETS | 0.41 | 0.39 | 0.54 |
| TabPFN-TS-3 | 0.32 | 0.27 | 0.40 |
| seasonal naive | 0.00 | −0.10 | −0.06 |

**No forecaster fully tracks a regime change, even six months in.** TabICL
adapts best (~0.7) but noisily; TabPFN-TS — the calibrated P1 winner — is
the *most conservative* (its seasonal anchoring holds it to the old regime).
Consequence for simulate: what-if must run through **explicit lever
conditioning**, never through the forecast read-out alone.

## P5 Leg B — what-if with the lever as a feature (the app-#2 gate)

Supervised conditional: context = post-lever rows of the support worlds
(factor column is the only between-world signal; pre-lever history identical
within a seed — the pure what-if shape). Query = held-out worlds.

| engine | query | effect recovered | WAPE | cover@80 | width@80 |
|---|---|---|---|---|---|
| **TabICL v2** | in-support 1.10 | **1.011** | **0.006** | **0.948** | 43k |
| | out-of-support 0.50 | 0.656 | 0.344 | 1.000 | **744k (17×)** |
| | out-of-support 1.50 | 0.629 | 0.130 | 0.927 | **1,016k (24×)** |
| TabPFN-3 | in-support 1.10 | 0.931 | 0.006 | 0.865 | 24k |
| | out-of-support 0.50 | 0.653 | 0.347 | **0.000** | 187k |
| | out-of-support 1.50 | 0.945 | 0.021 | 1.000 | 285k |
| TabFM | in-support 1.10 | 0.841 | 0.014 | — | — |
| | out-of-support 0.50 | 0.196 | 0.804 | — | — |
| LGBM quantile | in-support 1.10 | 0.563 | 0.056 | 0.375 | 158k |
| | out-of-support 0.50 | 0.288 | 0.712 | 0.010 | — |

Findings:

1. **In-support what-if passes, decisively.** TabICL recovers the held-out
   interpolated effect at 1.011 with near-zero error and near-nominal
   coverage. The classical baseline cannot do this at all (0.563 at 0.375
   coverage — trees don't interpolate a continuous lever from 7 observed
   values). This is the measured green light for app #2.
2. **Out-of-support, TabICL is the honest engine**: it under-extrapolates
   (0.63–0.66 of the true effect — regression toward the observed range)
   but *says so* — intervals widen 17–24× and coverage holds. Exactly the
   support-boundary behavior the architecture doc demands ("does uncertainty
   widen where evidence ends").
3. **TabPFN-3 can be confidently wrong out-of-support**: on the downside
   query its 80% interval covered **0.0%** of true values (bands 8× narrower
   than TabICL's at similar point error). The danger mode P5 was designed to
   surface, now quantified.
4. TabFM (point-only): fine in-support (0.841), collapses out-of-support
   (0.196), no uncertainty signal by construction — consistent with its
   demotion.

## Consequences for the applications

- **App #1 (scenario input generator)**: unchanged, gate passed in Phase 1.
- **App #2 (what-if read-out)**: gate **passed in-support** on TabICL.
  Build constraint from Leg B: what-if queries must carry a support-boundary
  guard — flag (and widen/refuse) queries whose lever value lies outside the
  observed context range; TabICL's own interval widening is the signal and
  it is trustworthy *for TabICL specifically* (not for TabPFN).
- **App #3 (scenario row generation): CUT** at the fidelity gate.

## Recorded caveats

- Leg B's support worlds span one DGP family, two seeds; the factor is the
  only conditioning lever tested. Multi-lever interaction (price × terms) is
  future work if app #2's build needs it.
- Leg A's non-monotone TabICL adaptation (0.61 → 0.34 → 0.69) is within
  cross-factor noise at n=6 runs per cell; the qualitative ordering
  (TabICL > ETS > TabPFN > naive) is stable across cells.
- The phase-2 result rows live under `tfm/output/phase1/` (the shared
  results store) — directory name is historical.
