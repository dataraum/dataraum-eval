# Phase 1 findings — probe harness + P1–P4, P6 (DAT-743, 2026-07-13)

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
| **TabPFN-TS-3** | 0.276 | **49,916** | **0.816** | **0.965** | 22.3 s |
| LGBM quantile | **0.272** | 52,218 | 0.651 | 0.852 | 34.8 s |
| ETS | 0.336 | 58,695 | 0.795 | 0.933 | 1.1 s |
| TabICL v2 forecaster | 0.331 | 58,935 | 0.759 | 0.922 | 12.4 s |
| seasonal naive | 0.367 | 66,310 | 0.761 | 0.897 | 0.04 s |

**Verdict material:** TabPFN-TS-3 has the best distributional forecast
(best CRPS) *and* near-nominal calibration at both interval widths — the
Phase-0 toy-coverage worry (0.72@80) does not reproduce on a proper
multi-origin measurement. LightGBM matches its point accuracy (WAPE) but is
badly overconfident (65% empirical at nominal 80%). TabICL v2's forecaster
lands at ETS level — no edge on this corpus. Horizon degradation is mild
for TabPFN (h1 0.257 → h3 0.282 WAPE) and absent-to-noisy for baselines.

## P2 — structure recovery (feature importance vs constructed formulas)

<!-- PENDING: tabicl2/tabpfn3 runs -->
LightGBM gain-importance baseline: `net_amount` Spearman 0.79 / Kendall 0.69,
`tb_debit_balance` 0.66 / 0.58 — and `top_k_exact` on both (the formula
features rank strictly above every distractor and noise column).

## P3 — density anomaly vs entropy_map labels (the payoff probe)

Setting: unsupervised, fit on the contaminated table itself (the detector
suite's own reality). Scored per (corpus, table, shaping bare/enriched) on
≤4,000-row seeded subsamples; per-injection-type AUROC/AP/precision@budget
with other types' rows excluded from the negatives.

IsolationForest baseline: near-chance or below on journal_lines (AUROC
0.31–0.55 per type at medium) — one-hot + tree partitioning does not see
these defects.

<!-- PENDING: tabicl2 sweep, tabpfn3 sweep, detector head-to-head -->

## P4 — exogenous conditioning (calendar signal + fx negative control)

Supervised framing: predict monthly account activity from autoregressive
base features; add {month} (real constructed signal) or {fx monthly means}
(no coupling exists). Temporal split, test = last 9 months (one full Q4).

LightGBM: base WAPE 0.309 → +calendar 0.285 (**+7.8% lift**, the real
signal found) → +fx 0.292 (**+5.5% "lift"** — on a corpus where fx carries
zero causal signal). The negative control fires: seeded fx random walks are
(seed, month)-indexed, so a flexible learner uses them as a *time-index
proxy* (trend leakage), not as fx. A capability evaluation without the
known-DGP control would have reported "fx conditioning helps" — this is the
strongest argument for the closed-loop corpus in the whole phase.

<!-- PENDING: tabicl2/tabpfn3/tabfm rows -->

## P6 — imputation (MCAR 10%/20%)

Baselines: mean/mode NRMSE≈1.00 (by construction), accuracy 0.57–0.59;
kNN-on-codes worse on both axes (heavy-tailed amounts, ordinal-coded
categoricals).

<!-- PENDING: tabicl2/tabpfn3 rows -->

## Data efficiency + latency (scorecard raw material)

LightGBM: classification acc 0.874@100 → 0.888@1000 rows (invoice pool caps
at 2k train); regression R² **−0.15@100** → 0.09@1k → 0.21@10k. The
small-context weakness the TFM literature targets is real for the GBM.

<!-- PENDING: TFM tiers -->

## Recorded gaps (per design: gaps are results, not workarounds)

- TabFM: no forecast, no quantiles, no density, no imputation, no
  importance read-out → absent from P1/P2/P3/P6 by design; participates in
  P4 supervised + tiers.
- TabPFN forecast covariates: supported by `predict_df` but calendar
  features are *built into* both TS pipelines (`CalendarFeature`,
  `AutoSeasonalFeature`) — the forecast-side provide/withhold experiment is
  therefore not clean for calendar; the supervised framing carries that
  comparison instead.
- `corrupt_dates` (payments/invoices) relabels 100% of a table's rows —
  no within-table negative class; recorded as coverage, not scored.

## Harness engineering notes

- **lightgbm × torch in one process aborts on macOS** (duplicate OpenMP
  runtimes) — the P1 run died mid-flight until baseline and TFM invocations
  were process-separated. The probe CLIs default accordingly; never re-mix.
- Both TS `predict_df` implementations require a NaN `target` column in
  `future_df` despite docs saying otherwise; both echo `target` back in
  the prediction frame (merge collision if kept).
- TabICL's conditional sampler crashes on constant columns
  (`currency`=USD) — P3 shaping drops zero-information constants.
- TabPFN SHAP via `shap.PermutationExplainer` costs O(features) full-context
  predicts per explained row — bounded to 200 explained rows.
