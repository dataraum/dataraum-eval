# Phase 0 findings — engine spike (DAT-742, 2026-07-13)

Environment: isolated uv project (Python 3.13), torch **2.13.0**, `device="mps"`
throughout (Metal SDPA/flash-attention path verified in `phase0/env_check.py`).
Engines: tabpfn 8.1.0 · tabicl 2.1.1 (v2 checkpoints) · tabfm 1.0.1 (git,
PyTorch backend) · skrub 0.10.0. Corpus: existing `data/clean` month-end-close.
Machine: MacBook Pro, Apple Silicon, 48 GB RAM.

## License verdicts

| Engine | Code | Weights | Verdict for this epic |
|---|---|---|---|
| TabPFN | Prior Labs License (Apache-2.0 + attribution) | **TabPFN-3/2.5/2.6 non-commercial** (TABPFN-3 License v1.0); TabPFN-2 Apache-2.0 | OK — internal benchmarking/evaluation explicitly permitted; product integration would need a commercial license. V3 weights **gated**: one-time login at https://ux.priorlabs.ai + `TABPFN_TOKEN` |
| TabICL | BSD-3-Clause (`forecast/` Apache-2.0, derived from TabPFN-TS) | HF, ungated | OK — permissive |
| TabFM | Apache-2.0 | HF `google/tabfm-1.0.0-pytorch` (~6.1 GB), ungated | OK — permissive |

## Engine × read-out inventory (measured on mps, toy runs on the shaped corpus)

| read-out | TabPFN | TabICL v2 | TabFM |
|---|---|---|---|
| classification | OK 13s, acc .904¹ | OK 3s, acc .908 | OK 70s, acc .907 |
| regression | OK 15s, R² .31¹ | OK 3s, R² .31 | OK 129s, R² .33² |
| quantiles | OK native, 80% cover .81¹ | OK native, 80% cover .74 | — point only |
| forecast | — (separate `tabpfn-time-series` pkg) | OK `TabICLForecaster`, quantile bands (27 account series, h=3) | — |
| anomaly (density) | — (via `tabpfn-extensions`) | OK `TabICLUnsupervised.score_samples` log-density | — |
| imputation | — (via `tabpfn-extensions`) | OK `TabICLUnsupervised.impute` | — |
| feature importance | — (via `tabpfn-extensions`, SHAP) | OK `tabicl.shap` (all-NaN column masking) | — |

¹ TabPFN rows measured on the **TabPFN-2 fallback** (Apache-2.0, ungated) — V3
auth pending, see caveats. ² With a harness-side float32 cast, see caveats.

**Headline: TabICL v2 is the only engine with the full native read-out surface —
including the density-based anomaly read-out P3 needs — and it is ~4× faster
than TabPFN and ~30× faster than TabFM at these toy sizes.** TabPFN reaches
anomaly/importance/forecast only via extension packages (Phase 1 should add
`tabpfn-extensions`). TabFM is classification/regression only, point
predictions — for P1/P3–P6 it participates only via prediction-based
workarounds, which per the design doc we record as gaps rather than build.

## Shaping notes (skrub 0.10)

Ledger from `phase0/shape.py`: 8 skrub steps / 7 hand steps.

- **skrub earns its place** for `Cleaner` (dtype + date parsing), `AggJoiner`
  (child-table aggregates onto a parent), `DatetimeEncoder` (date expansion).
- **Hand residue**: exact FK joins stay pandas `merge` — skrub's `Joiner` is a
  *fuzzy* joiner and the wrong tool for exact keys; leak-column drops
  (`debit`/`credit` decompose the `net_amount` target); derived quantities
  (`days_until_due`, `net_balance`); target extraction.
- Three shaped tables: `invoice_status` (5-class), `journal_line_amount`
  (regression), `monthly_account_series` (P1 substrate, 27 accounts × 12 months).

## Recorded caveats

- **TabPFN-3 gated weights**: non-interactive runs raise `TabPFNLicenseError`
  with instructions (login → accept license → `TABPFN_TOKEN`). One-time; token
  cached under `~/.cache/tabpfn/`. Until then the harness falls back to
  TabPFN-2 automatically, and V3 inventory rows are pending.
- **TabFM regression × MPS bug**: float64 `y` crashes — the device move precedes
  the model's own float64→float32 guard (`classifier_and_regressor.py:1801`).
  Harness feeds float32; trivially upstream-fixable.
- **TabFM speed**: ~70–130 s per fit+predict on 2–4k rows (6 GB bf16 model) vs
  3–15 s for the others.
- Toy metrics are **plumbing proof, not measurements** — single split, no
  baselines, no calibration claims. Phase 1 (DAT-743) owns measurement.
