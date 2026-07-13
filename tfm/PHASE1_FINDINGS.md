# Phase 1 findings — probe harness + P1–P4, P6 (DAT-743, 2026-07-13/14)

Environment: as Phase 0 (isolated uv project, torch 2.13.0, `device="mps"`),
plus `tabpfn-extensions` 0.4.2, `tabpfn-time-series` 1.2.0 (TabPFN-TS-3
checkpoint), `lightgbm` 4.6.0, `statsmodels` 0.14.6. All probe code under
`tfm/phase1/`; raw results in `tfm/output/phase1/*.jsonl` (append-only, one
row per engine × config, latencies included); aggregate views via
`report.py`. Corpora regenerable via `generate_corpora.py` (parent env).

## Substrate facts established from testdata code (load-bearing)

1. **The DGP has no fx→amount coupling.** `fx_rates` is a standalone table;
   every monetary amount is drawn in USD and no generator consumes `FXRate`
   (generators.py:1023–1049). The only fx→amount link anywhere is the
   `mix_units` *injection* (a constant factor on sampled rows). P4's fx leg
   is therefore a **negative control** by construction, and the missing
   coupling is a generator gap worth closing in the DAT-744 lever build if
   P4-style probes should ever have a real fx ground truth.
2. **The constructed calendar sensitivity is real**: `q4_seasonal_boost=0.3`
   lifts Q4 sales counts (generators.py:303) — measured +22% mean |activity|
   in Q4 across the 48-month corpora.
3. **P2 ground truth is exact**: `net_amount = debit − credit`
   (models.py:81–85); `trial_balance.{debit,credit}_balance =
   Σ journal_lines.{debit,credit}` over POSTED entries per (account, period)
   (generators.py:1055–1102) — recomputing it on clean data correlates
   1.0000 with the stored column.
4. **Longer histories are config-only** as the design doc claimed:
   `run_scenario(months=48, seed=…)`; 13 corpora generated in seconds
   (5 × 48-month clean seeds; clean/low/medium/high × 2 seeds at 12 months).
5. The vendor's own `low/medium/high` strategies ARE the design doc's
   severity ladder — no new strategy authoring; eval mirrors
   (`strategies/tfm-{low,medium,high}.yaml`) exist so the detector pipeline
   runs on **byte-identical data** (verified with `cmp`) to the TFM corpora.
6. Testdata uses PEP 758 unparenthesized `except ValueError, TypeError:`
   (Python 3.14+) — generation must run in the parent env, never the
   tfm venv (3.13). (An explorer agent — and past-me — misread this as
   Python-2 residue; it is committed, working 3.14 code.)

## P1 — probabilistic forecasting (monthly account activity, h=1–3)

135 series (27 accounts × 5 seeds) × 48 months; rolling origins
{36, 39, 42, 45}; quantile grid {0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975}.
Mean over origins, pooled over items/horizons (n=405 per origin):

| engine | WAPE | CRPS | cover@80 | cover@95 | latency/origin |
|---|---|---|---|---|---|
| **TabPFN-TS-3** | 0.276 | **49,916** | **0.816** | **0.965** | 22.5 s |
| LGBM quantile | **0.272** | 52,218 | 0.651 | 0.852 | 34.8 s |
| ETS | 0.336 | 58,695 | 0.795 | 0.933 | 1.1 s |
| TabICL v2 forecaster | 0.331 | 58,935 | 0.759 | 0.922 | 12.2 s |
| seasonal naive | 0.367 | 66,310 | 0.761 | 0.897 | 0.04 s |

**Verdict material:** TabPFN-TS-3 has the best distributional forecast
(best CRPS) *and* near-nominal calibration at both interval widths — the
Phase-0 toy-coverage worry (0.72@80) does not reproduce on a proper
multi-origin measurement. LightGBM matches its point accuracy (WAPE) but is
badly overconfident (65% empirical at nominal 80%). TabICL v2's forecaster
lands at ETS level — no edge on this corpus. Horizon degradation is mild
for TabPFN (h1 0.257 → h3 0.282 WAPE) and absent-to-noisy for baselines.

### Conformal addendum (CQR)

Split-conformal (Romano et al. 2019): calibrate on origins {36, 39},
evaluate on {42, 45} (n=810 each; temporal split, so exchangeability holds
only approximately — the honest deployment shape):

| engine | interval | cover pre | cover post | width cost |
|---|---|---|---|---|
| TabPFN-TS-3 | 80% | 0.800 | 0.767 | ×0.98 (narrowed) |
| TabPFN-TS-3 | 95% | 0.959 | 0.940 | ×0.99 |
| TabICL v2 | 80% | 0.740 | 0.760 | ×1.02 |
| TabICL v2 | 95% | 0.914 | 0.933 | ×1.05 |

Read: **TabPFN-TS needs no conformal wrapper** — it is already at nominal,
and a static correction learned on earlier origins slightly *hurts* it on
later ones. **CQR moves TabICL toward nominal (+2 pp at both levels, ≤5%
width cost) but a static calibration vector does not fully close the gap
under temporal drift** — later origins are harder, so the early-window
correction under-corrects. The named next step if TabICL is to be the
calibrated open engine: adaptive conformal (ACI, Gibbs & Candès 2021),
recalibrating the correction each period — plus fine-tuning for the
accuracy gap, with this probe as the standing gate.

## P2 — structure recovery (feature importance vs constructed formulas)

Rank agreement of mean-|SHAP| (TFMs) / gain importance (LGBM) against
formula membership, distractor + pure-noise columns included:

| target | engine | Spearman | Kendall | top-k exact | latency |
|---|---|---|---|---|---|
| net_amount | LGBM / TabICL / TabPFN | 0.791 (all three) | 0.690 | yes, all | 3 s / 35 min / **3.0 h** |
| tb_debit_balance | LGBM / TabICL / TabPFN | 0.655 (all three) | 0.577 | yes, all | 1 s / 98 s / 1.6 h |

**All three methods recover the constructed formulas exactly** — the
formula features rank strictly above every distractor and noise column, and
the three importance rankings agree with each other rank-for-rank. On this
corpus the TFM SHAP read-out adds no *quality* over LGBM gain importance —
it adds only cost (TabPFN's shap PermutationExplainer: hours). Sub-1.0
agreement against the binary truth reflects distractor ordering below the
formula features, identical across methods.

## P3 — density anomaly vs entropy_map labels (the payoff probe)

Setting: unsupervised, fit on the contaminated table itself (the detector
suite's own reality); ≤2,000-row seeded subsamples; per-injection-type
AUROC with other types' rows excluded from the negatives.

Journal_lines per type (bare shaping; low → medium → high severity):

| injection type | TabICL v2 | TabPFN-3 ext. | IsolationForest |
|---|---|---|---|
| corrupt_type | 0.99 / 0.995 / 0.97 | **0.11 / 0.19 / 0.18 (inverted)** | 0.44–0.48 |
| inject_outliers | 0.98 / 0.85 / 0.81 | 0.96 / 0.83 / 0.75 | 0.47–0.53 |
| break_referential_integrity (high) | 0.954 | 0.205 | 0.387 |
| add_duplicate_fk_paths (high) | 0.945 | 0.814 | 0.415 |
| create_mutual_exclusivity | 0.70–0.74 | 0.60–0.69 | 0.45–0.53 |
| introduce_nulls | 0.50–0.61 | 0.42–0.47 | ~0.30 |

Distribution-level and cross-table types (benford, temporal_drift,
gl_invoice_match, mix_units, trial-balance formula breaks) sit at
0.43–0.55 for every scorer — **row-wise density cannot see them**, exactly
as theory predicts.

Findings:

- **TabICL v2 is the only credible density engine.** Strong on row-visible
  corruption; monotone degradation as contamination rises (outliers
  0.98 @ 2% → 0.81 @ 15% — the density absorbs heavy contamination into
  "normal", the classic unsupervised limit).
- **TabPFN's unsupervised read-out anti-detects type corruption**
  (AUROC 0.11–0.20): its `outliers()` sums per-feature conditional
  log-densities and missing/NaN cells drop out of the sum, so rows with
  corrupted (→NaN) cells look *denser*. Recorded as a read-out defect, not
  worked around.
- **The RI hit is a rare-category proxy, not referential reasoning**: the
  injector writes once-occurring `ORPHAN-nnnnnn` values
  (injectors.py:654–690), and a once-seen category collapses row density.
  A single repeated orphan value or valid-but-wrong FK swaps would defeat
  it; the suite's `relationship_entropy` actually joins the parent. (Cheap
  Phase-2 falsification probe available: repeated-orphan + shuffled-FK
  variants.)
- **Reconstruction-gap enrichment fails under upstream corruption**: on
  clean data the recomputed TB aggregates match exactly, but on injected
  corpora journal_lines' own defects (outliers, corrupted types) swamp the
  gap — uninjected TB rows carry median |gap| ≈ 158k at high severity. This
  is why the detector suite's cross-table checks use matched-fraction
  statistics, not raw gaps.
- `corrupt_dates` touches 100% of a table's rows → no within-table negative
  class; recorded as coverage, not scored.

### Head-to-head with the detector suite (same injections, same data)

Pipeline runs on byte-identical corpora (`tfm-low/medium/high`, sidecars +
scores via the head-resolved read path). 47 injection rows in
`p3_headtohead.jsonl`. The two systems are **complementary, not
competing**:

| defect family | calibrated suite | TabICL density |
|---|---|---|
| nulls (cost_center) | **0.54 → 0.59 → 0.71 entropy, monotone in severity** | blind (≈0.5) |
| obscured names | **0.70 on every renamed column** | n/a (schema-level) |
| corrupt dates | 1.0 (low, high; 0.0 miss at medium — noted) | n/a (all-rows type) |
| corrupt types | weak (0.01–0.06) but null_semantics fires 0.31–0.33 | **0.97–0.995** |
| outliers | **no live detector** (outlier_rate CUT at the ground gate) | **0.81–0.98** |
| unit mixes (fx-scaled) | 0.0 — the known DAT-647 migration gap | blind (subset scale shift is in-distribution row-wise) |
| RI orphans | relationship_entropy 0.15 @ high (semantically grounded) | 0.954 (rare-category proxy) |
| TB formula breaks | derived_value/cross-table not scored on these runs | blind row-wise |

The sharpest complementarity: **outlier bursts, where the suite deliberately
has no detector, are the density read-out's best class** — a TFM witness
would cover exactly the hole the ground-first kill gate left. Conversely,
everything the suite is calibrated on (nulls, names, units-as-semantics,
cross-table identities) stays invisible to single-table density.

## P4 — exogenous conditioning (calendar signal + fx negative control)

Supervised framing, autoregressive base features (no calendar channel);
temporal split, test = last 9 months (one full Q4); WAPE lift vs base:

| engine | base WAPE | +calendar lift | +fx "lift" (no real signal) |
|---|---|---|---|
| TabICL v2 | 0.272 | **+6.2%** | **−0.1%** |
| TabPFN-3 | 0.271 | **+6.8%** | **+0.3%** |
| TabFM | 0.272 | **+6.6%** | +1.5% |
| LGBM | 0.309 | +7.8% | **+5.5% (spurious)** |

**All three TFMs find the real constructed signal AND pass the negative
control that fools the GBM.** The seeded fx random walks are (seed,
month)-indexed, so a flexible learner can exploit them as a time-index
proxy — LGBM does (+5.5% on a corpus with zero fx→amount coupling); the
in-context learners essentially ignore them. A public-benchmark evaluation
without the known-DGP control would have reported "fx conditioning helps"
as a capability. Also: every TFM's *base* WAPE (0.271–0.272) beats LGBM's
(0.309) at 3k context rows. Residual-bias profiles add nothing (biases are
1–2% of target scale everywhere) — lift, not bias collapse, is the
measurable footprint at this corpus size.

## P6 — imputation (MCAR 10% / 20% on mixed columns)

| method | NRMSE numeric (10/20%) | categorical acc (10/20%) | latency |
|---|---|---|---|
| **TabICL v2** | **0.90 / 0.97** | **0.75 / 0.73** | 11 s |
| TabPFN-3 ext. | 1.52 / 1.72 | 0.68 / 0.62 | 380–412 s |
| mean/mode | 1.00 / 1.00 | 0.57 / 0.59 | ~0 |
| kNN (codes) | 1.21 / 1.14 | 0.51 / 0.47 | 0.1 s |

TabICL is the only method beating the trivial baseline on **both** axes,
at interactive latency. TabPFN's extensions imputer is *worse than the
column mean* on numerics here, at ~400 s — recorded as measured.

## Data efficiency + latency (scorecard raw material)

Held-out test, context tiers (classification caps at 2k train pool —
invoices has 3,000 rows):

| task, metric | context | TabPFN-3 | TabICL v2 | TabFM | LGBM |
|---|---|---|---|---|---|
| clf accuracy | 100 | 0.898 | 0.899 | 0.898 | 0.874 |
| | 1,000 | **0.906** | 0.896 | 0.909 | 0.888 |
| reg R² | 100 | **0.130** | 0.023 | −0.016 | −0.153 |
| | 1,000 | 0.288 | **0.301** | 0.290 | 0.090 |
| | 10,000 | 0.332 | **0.330** | 0.303 | 0.210 |

The literature's small-context claim is real here: at 100 rows every TFM
classifies ~2.5 pp above LGBM (with far better log-loss: 0.33–0.38 vs
0.76), and TabPFN turns a positive regression R² where LGBM is negative.
The gap persists at 10k (TFM R² 0.30–0.33 vs 0.21). Latency: TabICL
0.7–10 s, TabPFN 1.2–14 s per tier; TabFM 36–419 s (the 6 GB bf16 model
pays per call).

## Recorded gaps (per design: gaps are results, not workarounds)

- TabFM: no forecast, quantiles, density, imputation, or importance
  read-out → absent from P1/P2/P3/P6 by design; measured in P4 + tiers.
- TabPFN forecast covariates: calendar features are built into both TS
  pipelines — the forecast-side provide/withhold experiment is not clean
  for calendar; the supervised framing carries that comparison.
- TabPFN unsupervised: NaN-handling defect above (upstream-reportable).
- `clean`-workspace pipeline failure → DAT-748 (typing breaks in
  workspaces with catalog history; fresh workspace on identical bytes is
  green — isolated with `tfm-clean`).

## Harness engineering notes

- **lightgbm × torch in one process aborts on macOS** (duplicate OpenMP
  runtimes) — baseline and TFM invocations are process-separated; the P1
  run died mid-flight until they were.
- Both TS `predict_df` implementations require a NaN `target` column in
  `future_df` despite docs, and echo `target` back in the output.
- TabICL's conditional sampler crashes on constant columns — P3 shaping
  drops zero-information constants.
- `corrupt_type` injects float64-max-scale tokens: they overflow float32
  encoding to inf and fail sklearn validation — encode maps non-finite to
  NaN (the NaN itself remains the anomaly trace).
- TabICL SHAP: `get_shap_values` explains every row given; bounded to 200
  rows + `kv_cache=True` after the 35-min unbounded run. Measured:
  **2,096 s → 22.5 s (93×)** on net_amount, 98 s → 12.6 s on tb_debit,
  with identical rank agreement — the KV cache pays the context encoding
  once across SHAP's thousands of replayed predicts.
- TabPFN SHAP via `shap.PermutationExplainer` is hours-scale on MPS even
  bounded (3.0 h / 1.6 h per target) — if P2-style read-outs recur, move
  to shapiq budgeted approximators or a CUDA box.

## Phase-2/3 pointers surfaced by this phase

- TabICL is the only engine with the full read-out surface AND the full
  open evolution loop: `tabicl._finetune` (meta-batch fine-tuning),
  `tabicl.prior` (the synthetic SCM prior generator, runnable), and
  `tabicl.train` (pretraining) all ship under BSD-3 with ungated weights.
  TabPFN-3 weights are non-commercial (fine-tunes inherit that); TabFM has
  no training code.
- Calibration route for TabICL's under-coverage: CQR conformal wrapping
  (see addendum) before any fine-tuning — fine-tune for accuracy,
  conformalize for calibration.
- P3 falsification probe (cheap): repeated-orphan + valid-but-shuffled FK
  variants to show the density RI hit is a rare-category proxy.
- fx→amount coupling in the generator (DAT-744-adjacent) would give P4 a
  real positive fx ground truth to complement the negative control.
