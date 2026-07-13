# TFM track — DAT-741

Hands-on capability evaluation of tabular foundation models on the known-DGP
corpus. Design doc: [TFM Capability Evaluation](https://real-dataraum.atlassian.net/wiki/spaces/DD/pages/49414145/TFM+Capability+Evaluation)
(Confluence DD). This directory is an **isolated uv project** — its own
`pyproject.toml`, Python 3.13, and `.venv` — so the torch/engine stack never
touches the calibration environment (parent repo pins Python 3.14; the ML wheel
ecosystem is safest on 3.13, and nothing here imports the engine).

```bash
cd tfm
uv sync
uv run python phase0/env_check.py      # torch/MPS/SDPA + engine imports
uv run python phase0/shape.py          # corpus -> model-ready flat tables (+ shaping ledger)
uv run python phase0/toy_tabpfn.py     # per-engine toy runs; write inventory JSON
uv run python phase0/toy_tabicl.py
uv run python phase0/toy_tabfm.py
uv run python phase0/inventory_report.py   # merged engine x read-out matrix
```

## Environment (Phase 0, 2026-07-13)

- **torch 2.13.0**, `device="mps"` everywhere — the 2.13 Metal SDPA /
  flash-attention kernels verified working in `env_check.py`.
- Engines: `tabpfn` 8.1.0 · `tabicl` 2.1.1 (v2 checkpoints) · `tabfm` 1.0.1
  (git, PyTorch backend) · shaping: `skrub` 0.10.0.
- Machine: MacBook Pro, Apple Silicon, 48 GB RAM.

## License verdicts (Phase 0 checkpoint)

| Engine | Code | Weights | Our use (internal capability eval) |
|---|---|---|---|
| TabPFN | Prior Labs License (Apache-2.0 + attribution) | **TabPFN-3/2.5/2.6: non-commercial** (TABPFN-3 License v1.0); TabPFN-2: Apache-2.0 | OK — "internal benchmarking … experimentation" is explicitly permitted; production/product use would need a commercial license. Weights are gated: one-time browser license acceptance (token cached under `~/.cache/tabpfn/`). |
| TabICL | BSD-3-Clause (`forecast/` subdir Apache-2.0, derived from TabPFN-TS) | HF Hub, ungated | OK — permissive |
| TabFM | Apache-2.0 | HF Hub (`google/tabfm-1.0.0-pytorch`), ungated | OK — permissive |

## Data

Inputs come from the already-generated clean corpus at `data/clean/` (regenerate
via `calibration.runner.generate("clean")` in the parent env). `phase0/shape.py`
writes model-ready tables to `tfm/output/shaped/`:

| table | task | target |
|---|---|---|
| `invoice_status` | classification (5 classes) | `status` |
| `journal_line_amount` | regression | `net_amount` (debit/credit dropped — direct leak) |
| `monthly_account_series` | P1 forecast substrate | `net_balance` per account × month |

Shaping division of labor (the ledger prints on every run): skrub `Cleaner`
(dtype/date parsing), `AggJoiner` (child-table aggregates), `DatetimeEncoder`
(date expansion); hand-written pandas for exact FK joins (skrub's `Joiner` is a
*fuzzy* joiner — wrong tool for exact keys), leak-column drops, and derived
quantities (`days_until_due`, `net_balance`).

Phase 0 verdicts, the full inventory matrix, and shaping notes:
[`PHASE0_FINDINGS.md`](PHASE0_FINDINGS.md) (mirrored into the DAT-741 epic).
