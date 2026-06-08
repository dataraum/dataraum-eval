# Entropy Eval — Architecture & Method

> **Status:** reset (2026-06-08). This supersedes the implicit "run the calibration
> suite until it's green" workflow. It is the definition of what eval *is* and how
> we develop entropy measurements.

## Why this document exists

We spent days tuning entropy measurements by **booting Postgres + Temporal + an LLM
pipeline (~10 min) to test pure math**, then guessing at the next tweak from slow,
noisy feedback. The result was a hack-and-compile loop — "shitty reality → shitty
reality" — with no convergence. Two root causes:

1. **The test pyramid was inverted.** A drift / conflict / surprise score is a *pure
   function*. It must be tested in **milliseconds** on synthetic + recorded data, not
   by re-running the whole framework.
2. **Eval drifted from purpose to proxy.** We optimized "does the injection score
   > 0.3 on one fixed dataset" instead of "is this measurement *right*, and does it
   tell a practitioner something *true and actionable*." That is Goodhart at the
   harness level.

This document fixes both.

## What eval proves

A measurement earns its place **only if all three hold**, and eval's job is to prove
each — fast:

| Property | Meaning | Proven by |
|---|---|---|
| **Right** | a grounded statistic, not an improvised boost curve | Tier 1 unit (synthetic) |
| **Useful** | tells the practitioner something *true and actionable* — enables a fix or teach, or is genuine **context** for a query / aggregation / report decision. If it tells nothing actionable, **cut it.** | the measurement contract (below) |
| **Stable** | a teach *closes* it (conflict/ignorance or score drops), provably | Tier 1 unit (teach-closure) |

"Scores an injection" is **not** a goal. It was the proxy we Goodharted. Recall is
asserted as **ordering / calibration** (injected > clean + margin; monotonic in
severity), never a point threshold.

## The test architecture — invert the pyramid

| Tier | Speed | Docker? | Proves | Where iteration happens |
|---|---|---|---|---|
| **1 — unit** | ms | no | the statistic as a pure fn over **synthetic** fixtures: clean < injected ordering, calibration shape, edge cases, **and teach-closure** | **ALL measure + teach design** |
| **2 — recorded** | sec | no | the statistic over **frozen real pipeline outputs** (the SQLite fixture below) — real data shapes, no pipeline | confirming the measure survives reality |
| **3 — integration** | min | yes | the **assembled** framework end-to-end (generate → pipeline → measure → readiness → teach) | wiring only; **milestone gate, NOT the dev loop** |

**Rule:** every measure and teach is designed and debugged in Tier 1/2. The live
suite (Tier 3) runs **once per milestone**, never per tweak.

> Worked example of the cost: "does KS separate a 1.35× shift from natural monthly
> volatility?" is a **2 ms Tier-1 test** on two synthetic samples. We answered it with
> 10-minute pipeline runs. Never again.

### The recorded fixture (Tier 2)

One live run produces real intermediate data; we **extract what the measures consume**
into a portable **SQLite** file committed to the repo (`calibration/fixtures/…`). It
holds, for both a **clean** and an **injected** session:

- raw per-period numeric **values** (for drift / KS) — from the DuckDB slice tables
- **quarantine tokens** + counts (for null_semantics) — from the DuckDB quarantine tables
- leading-digit **distributions** / numeric samples (for benford)
- per-slice **statistical profiles** (for dimensional_entropy) — from Postgres
- **witness distributions** (for pooling C/U) — from `claim_witnesses`
- **semantic annotations** (units, roles, null_tokens)

After capture, **no measure or teach is ever debugged through the live pipeline again.**
Refresh the fixture only when the pipeline's *output shape* changes (a schema/phase
change), via `scripts/capture_fixture.py`.

## The measurement contract

Written **before code**, one entry per measurement (see catalog below):

- **Purpose** — what does it tell the practitioner; what decision / context does it serve?
- **Earns its place?** — yes / conditional / cut. If it enables no fix/teach and is no real context, it is cut.
- **Statistic** — the grounded method.
- **Fix / teach** — the action that closes it.
- **Unit proof** (Tier 1) — synthetic ordering + calibration + teach-closure.
- **Recorded proof** (Tier 2) — assertion against the SQLite fixture.
- **Integration case** (Tier 3) — the one end-to-end scenario.

## Measurement catalog

The grounded statistic per measurement, and the honest "earns its place" call. The
**conditional / cut** rows are where the reset pays off — purpose-first kills or
reframes measurements that only ever produced noise.

| Measurement | Purpose / context it serves | Earns it? | Grounded statistic | Fix / teach |
|---|---|---|---|---|
| **null_semantics** | "is `#ERR` a null?" — don't silently aggregate contested markers | **yes** | pooling **C/U** over witnesses | null_value overlay → witness flips |
| **type_fidelity** | type-cast failures → structural trust | **yes** | raw quarantine **rate** (drop `_boost_rate`) | re-type / teach pattern |
| **null_ratio** | missing fraction → completeness | **yes** | raw **rate** | fill / document |
| **outlier_rate** | extreme-value fraction → aggregation risk | **yes** | IQR/MAD **rate**, raw (drop piecewise+CV-atten) | document expected range |
| **benford** | leading-digit anomaly → fabrication/rounding | **yes** (forensic context; current injection is weak) | **KL** surprise or **Nigrini MAD** | document expected pattern |
| **relationship_entropy** | orphan rate → join safety | **yes** | raw **orphan rate** (drop sqrt-boost) | fix FK / teach |
| **join_path_determinism** | ambiguous join paths → join safety | **yes** | **confidence-gated** candidate count (fix the over-fire) | pick the FK |
| **business_meaning** | garbage column names → interpretability | **yes** | LLM confidence → **pooling** (DAT-446) | name the column |
| **unit_entropy** | undeclared/ambiguous units → aggregation correctness | **yes** | declaration completeness → **pooling** (DAT-428) | declare the unit |
| **temporal_entropy** | broken time-role (unparseable dates) → time filtering | **yes** | type/role mismatch | re-type |
| **cross_table_consistency** | cross-table reconciliation breaks → correctness | **yes** | orphan / violation **rate** | fix / teach |
| **temporal_drift** | distribution shifted over time | **CUT** (DAT-442 reset) — meaningful only for **stationary / point-in-time** columns; transaction **flows** naturally vary (clean KS ≈ injected ≈ 0.53), so absolute drift can't separate a shift from noise. Real drift → DAT-445's **expected-variation** model. Proven: `calibration/unit/test_drift_recorded.py`. | two-sample **KS** / **PSI** vs an **expected-variation reference** | document expected seasonality |
| **slice_variance** | column behaves differently across slices | **CUT** (DAT-442 reset) — a between-slice k-sample test is structurally **blind to the slice-GLOBAL injections** the eval creates (Δη² ≈ 0.00 vs clean) and **saturates on legitimate cross-slice heterogeneity** of real financial data (clean η² ≈ 0.78). No grounded statistic rescues it; the old max-of-spreads fired only on non-injected columns. The one defensible sliver (null-rate-across-slices) is a proportions test (**Cramér's V**), deferred to DAT-184 + a slice-conditional-null injection. Proven: `calibration/unit/test_slice_variance_recorded.py`. | **Kruskal–Wallis** / ANOVA **η²** (insufficient) | document segmentation |
| **dimensional_entropy** | cross-column dependency (mutual exclusivity, …) | **conditional** — context for "these columns aren't independent." Earns it only if a downstream decision uses it. | normalized **mutual information** | document the rule |
| **dimension_coverage** | fact-table dimension completeness | **review** | coverage ratio | teach |
| **business_cycle_health** | business-cycle anomaly | **review** | (define) | teach |

## Rollout

1. **Capture the recorded fixture** (`scripts/capture_fixture.py` → `calibration/fixtures/entropy_inputs.sqlite`). One live run; docker once.
2. **Build the Tier-1/2 harness** — fixture loaders + assertion helpers (ordering, calibration, teach-closure) that need no docker.
3. **Per-measurement, purpose-first:** write the contract entry, then the Tier-1 unit (synthetic) + Tier-2 (recorded) tests, then the statistic. Cut / reframe the **conditional** rows honestly.
4. **Tier 3** becomes the milestone gate: the existing calibration suite, run when Tier 1/2 are green — proving wiring, not math.

## How to run

```bash
# Tier 1 + 2 — the dev loop (milliseconds, no docker):
uv run pytest calibration/unit -q              # synthetic + recorded-fixture tests

# Refresh the recorded fixture (only when pipeline output shape changes):
python scripts/capture_fixture.py              # docker stack up; one pipeline run

# Tier 3 — milestone gate (minutes, docker):
make calibrate                                  # full generate → pipeline → suite
```
