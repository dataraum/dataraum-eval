# Sonnet 5 swap gate — 2026-07-02 (DAT-602)

**Verdict: GO for the model swap.** No regression attributable to Sonnet 5. The
engine delta riding the same bump carries one real regression (same-workspace
re-run) and two open questions — all engine/contract items, none model items.
This report is the standing regression baseline for future model swaps.

## What was gated

Engine `63629f05` (post-#432 main): `claude-sonnet-5` default/balanced,
`claude-haiku-4-5` fast, `effort: low` on the mechanical extractors, strict on
`validation_sql`. **Not a pure model A/B** — the 56-commit delta from `a07fbc64`
also carries DAT-543 (operating model), DAT-647 (unit split), DAT-654 (sqlglot →
DuckDB parser), DAT-656, DAT-599. Attribution rule used throughout: pure-math
detector families are model-invariant (movement ⇒ code delta); only LLM-judgment
families and the financial leg can implicate the swap.

Lean gate (not `--all`): `clean` + `detection-v1` — detection-v1 alone injects
every swap-sensitive family (business_meaning, relationship_entropy,
derived_value, cross_table_consistency, unit_entropy). The 11 family-focused
strategies remain diagnosis tools, pulled only on a family regression. Plus a
3-seed clean resweep (46/47/48, isolated workspaces) to rebuild the precision
bands against the fixed detectors.

## Results

| Leg | Result |
|---|---|
| Tier 1/2 (unit + recorded) | 39/39 green |
| Recall grammar (detection-v1) | green — no failures; xfails are the documented pooled-LLM cases |
| Precision bands (rebuilt) | green except 11 novel-key emissions (below — LLM catalog variance, not scores out of band) |
| Readiness precision (clean) | green after one attributed rebaseline (fx_rates.rate, below) |
| Financial accuracy (injected data) | 5/5 deviating metrics flagged blocked by the rollup; grounded SQL (account-classification joins — DAT-616/652 signature holds) cut the predicted naive-path error 67% → 9.2% |
| Swap watch-list (effort:low / coercion / thinking-off / strict SQL) | no attributable quality signal in any leg |

Every moved score traced to a named engine fix, none to the model:

- `temporal_behavior` — was mis-wired (its clean band was **degenerate**: 0.5127
  across 3 seeds, i.e. constant, not reading data). Fixed detector now bands
  [0.002, 0.616] and correctly claims `fx_rates.rate` (single uncorroborated
  "stock" witness, ignorance 0.811 → aggregation investigate — **accurate**: an
  FX rate is a point-in-time ratio; naive aggregation is meaningless). Clean
  readiness baseline updated with that reasoning.
- `unit_entropy` — the DAT-647 false-block (degenerate 1.0×3 band) is gone;
  value-grain scores honest ~0 on clean; new catalogue-grain `unit_source`
  dispositioned (latent candidate; no injection family yet — /evolve-testdata gap).
- `relationship_discovery` / `relationship_entropy` — context-coverage fix makes
  the graph see real pairs; new measurement points banded by the resweep.

## Findings (engine/contract, in priority order)

1. **Same-workspace pipeline re-run broken post-#432** (the teach-and-rerun
   path). Reused parent workflow id (`ALLOW_DUPLICATE`, by design) + upserted
   `raw_table_id`s repeat the completed run's child workflow ids; Temporal
   reports children "already completed", typing activities are cancelled
   mid-SQL, phase fails. Reproduced by the sweep's old seed-0-in-place design;
   worked pre-delta (past sweeps). Would bite teach closures and production
   re-adds. Eval unblocked by isolating sweep seeds; **engine fix required
   before any teach-closure work.**
2. **Degeneracy lint added** (`build_clean_bands.py` + Tier-1 tests): a
   zero-width band across seeds on a continuous statistic now fails the build —
   both historical wiring bugs (temporal_behavior 0.5127×3, unit_entropy 1.0×3)
   sat in the blessed bands as exactly this signature. Discrete-by-design
   allowlist: `unit_source` (binary catalogue fact), `business_meaning`
   (quantized step map over seed-invariant names), `relationship_discovery`
   (witnesses saturate on clean pairs; recall ordering guards the moving case).
3. **LLM catalog-membership variance swings whole measurement points** (open
   contract question): 11 keys exist on the live run and in zero sweep seeds.
   Sharpest case: `journal_entries.date:relationship_entropy` 0.529 live vs
   ~0.001 in sweeps — the band key hides the PARTNER column; pairing a date
   column with weekday-only `fx_rates.date` reads calendar gaps as orphans.
   Fork to decide: (a) pooled per-detector fallback for novel keys at
   LLM-membership grains, (b) whether date↔date pseudo-joins belong in the
   relationship catalog at all.
4. **`journal_entries:dimension_coverage` 0.748 live vs 0.0×3 sweeps** — a real
   outlier, annotation-coverage-driven; uninspectable via the direct tools
   (measure dumps no table grain — tool-surface gap). Open.
5. **Loss-weight question, now with evidence**: a 20% orphan rate on
   `payments.invoice_id` leaves all intents *ready* (`relationship_entropy`
   weighs reporting 0.75 only → 0.15). `loss.yaml` already flags the weight as
   a known calibration question.
6. **Cost structure**: the lean gate spent ~15% of `calibrate-all` and lost no
   coverage. Proposed for the Haiku phase: content-keyed LLM record/replay at
   the provider seam (engine ticket) — per-feature A/Bs then pay only the
   feature under test.

## Reproduction

```
uv run python -m calibration.run -s clean,detection-v1     # the gate
uv run python scripts/sweep_clean_seeds.py                 # bands input (isolated seeds)
uv run python scripts/build_clean_bands.py                 # rebuild + degeneracy lint
uv run pytest calibration/ --strategy clean|detection-v1   # assertions off persisted runs
```

Engine-bump preflight learned this gate: **reset the eval stack after any bump
that touches `db_models`** (round 1 died on `lifecycle_artifacts.graph_definition`
missing from a pre-delta workspace schema; every downstream "regression" was
noise from the crashed validation phase).
