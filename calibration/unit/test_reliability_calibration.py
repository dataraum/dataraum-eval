"""Witness reliability calibration — the DAT-450 rig, tier-2 (ms, no docker).

Proves the calibration rig end-to-end against the generative null_tokens family:

* **measurement** — the rig produces a reliability per witness from labelled family
  samples, by running the REAL engine witnesses (no reimplementation).
* **AC4 calibration** — proper scoring on held-out seeds. We instantiate "witness
  confidence correlates with correctness" as its stronger aggregate form: the
  POOLED posterior Brier (a strictly proper scoring rule) under the measured r,
  measured on seeds disjoint from the fit corpus, must beat (a) uniform weights —
  calibrated, not just firing — (b) the always-abstain baseline 0.25 — informative
  — and (c) the placeholder priors — un-stubbing improved resolution, DAT-450's
  actual purpose. All relative/baseline (Goodhart-safe), never a tuned threshold.
  (We deliberately do NOT assert a per-witness confidence-vs-accuracy ordering: it
  legitimately fails on the pooled population because type_claim is a confidently
  MIS-calibrated witness — the rig's honest finding, surfaced in its low r, not
  hidden.) The held-out seeds are disjoint but draw novel sentinels from the same
  bounded grammar, so this guards the fitted SCALARS, not an unseen token universe.
* **AC5 monotonicity** — more corruption → more entropy: as a novel sentinel's
  rejected count rises, the pooled conflict C rises monotonically (replacing a
  former point threshold).
* **faithfulness** — the rig's input reconstruction matches the REAL pipeline
  loader SQL (``rejected_token_counts`` + the ``failed_examples`` DISTINCT…LIMIT 5
  query), so the fast isolated rig is not a drifting reimplementation.
"""

from __future__ import annotations

import duckdb
import pytest
from dataraum.entropy.detectors.loaders import rejected_token_counts
from dataraum.entropy.measurements.null_semantics import (
    DEFAULT_RELIABILITIES,
    measure_null_semantics,
)
from testdata.entropy.families import (
    CURATED_VOCAB,
    NullTokenFamilyParams,
    sample_null_token_family,
)

from calibration.reliability_rig import (
    LabeledToken,
    calibrate,
    collect_adjudications,
    estimate_reliabilities,
    per_class_accuracy,
    pooled_brier_with,
    realize_population,
    reconstruct_inputs,
    witness_votes,
)

_WITNESSES = {"quarantine_clustering", "type_claim", "null_vocabulary"}
_FIT = range(0, 80)
_HOLDOUT = range(5_000, 5_040)


def test_rig_measures_a_reliability_per_witness_in_range() -> None:
    result = calibrate(list(_FIT))
    assert set(result.reliabilities) == _WITNESSES
    assert all(0.0 <= r <= 1.0 for r in result.reliabilities.values())
    # The measurement is not a no-op: it moves OFF the placeholder priors (the
    # whole point of DAT-450 — un-stub the inline constants with measured values).
    assert result.reliabilities != pytest.approx(
        {k: float(v) for k, v in DEFAULT_RELIABILITIES.items()}, abs=0.02
    )


def test_held_out_reliabilities_beat_uniform_baseline_and_placeholder() -> None:
    """AC4 — proper scoring on held-out seeds (see module docstring).

    Fit r on the fit corpus; on disjoint held-out seeds the measured r must pool to
    a lower Brier than uniform weights, the always-abstain baseline, AND the
    placeholder priors it replaces."""
    measured = estimate_reliabilities(witness_votes(collect_adjudications(_FIT)))
    holdout = collect_adjudications(_HOLDOUT)

    brier_measured = pooled_brier_with(holdout, measured)
    brier_uniform = pooled_brier_with(holdout, dict.fromkeys(measured, 0.5))
    brier_placeholder = pooled_brier_with(
        holdout, {k: float(v) for k, v in DEFAULT_RELIABILITIES.items()}
    )

    assert brier_measured < brier_uniform  # calibrated weights resolve better
    assert brier_measured < 0.25  # beats always-abstain (the adjudication is informative)
    assert brier_measured < brier_placeholder  # un-stubbing the constants IMPROVED resolution


def _conflict_for_marker_count(marker_count: int) -> float:
    """Pooled conflict C on a fixed NOVEL sentinel as its rejected count varies.

    A novel sentinel (sorts last → out of failed_examples[:5], so the type witness
    abstains) against a fixed decoy background: only quarantine (is-null, stronger
    with count) and vocabulary (is-value, fixed) speak, so their disagreement — the
    conflict — must grow with the corruption volume."""
    novel = "ZZ_NOVEL_SENTINEL"
    tokens = [LabeledToken(novel, marker_count, True)]
    tokens += [LabeledToken(f"EUR {i}.50", 1, False) for i in range(20)]
    quarantine, typing = reconstruct_inputs(tokens, n_rows=4000)
    adjudications = measure_null_semantics(quarantine, typing, list(CURATED_VOCAB))
    adj = next(a for a in adjudications if a.token == novel)
    return adj.result.conflict


def test_conflict_rises_monotonically_with_corruption_rate() -> None:
    """AC5 — rate-sweep monotonicity replacing a point threshold."""
    sweep = [_conflict_for_marker_count(c) for c in (5, 20, 50, 100, 250)]
    assert sweep == sorted(sweep)  # non-decreasing: more corruption → more entropy
    assert sweep[-1] - sweep[0] > 0.05  # and the movement is real, not flat noise


def test_stress_family_exposes_quarantine_specificity() -> None:
    """The decoy-clustering stress family closes the sensitivity-only honesty gap.

    With DISTINCT decoys, quarantine_clustering abstains on every is-value token, so
    its false-positive rate is structurally unmeasured. With CLUSTERED decoys it
    finally faces a repeated genuine value, votes is-null on it (it scores any
    cluster), and is wrong — so its specificity is now measured and is far below its
    sensitivity (it is a clustering detector, not a marker/genuine discriminator)."""
    stress = NullTokenFamilyParams(decoy_cluster_size=(2, 4))
    pc = per_class_accuracy(witness_votes(collect_adjudications(range(0, 40), params=stress)))
    quarantine = pc["quarantine_clustering"]
    assert "specificity" in quarantine  # it NOW opines on is-value (clustered) tokens
    assert quarantine["specificity"] < quarantine["sensitivity"]  # the FP rate is real


@pytest.mark.parametrize("resolved_type", ["BIGINT", "DECIMAL(18,2)", "DOUBLE"])
def test_reconstruction_matches_the_real_pipeline_loader(resolved_type: str) -> None:
    """Faithfulness anchor — the isolated rig reconstructs the SAME witness inputs
    the production loaders would, proven against the real loader SQL in-memory.

    Parametrized over the numeric types a financial column actually resolves to
    (journal_lines.debit / bank_transactions.amount are Decimal): the family's
    markers and decoys fail EVERY numeric cast, so the rejected set is type-invariant
    — and this guards that property rather than only the BIGINT path."""
    sample = sample_null_token_family(20260609)
    n_rows = 1500
    tokens = realize_population(sample, n_rows)
    total_rejected = sum(t.count for t in tokens)

    # Materialise the raw VARCHAR column the pipeline would stage: injected tokens
    # repeated by their count, the rest clean integers that cast cleanly.
    cells: list[str] = []
    for t in tokens:
        cells += [t.token] * t.count
    cells += [str(1000 + i) for i in range(n_rows - total_rejected)]
    conn = duckdb.connect()
    conn.execute("CREATE TABLE raw (debit VARCHAR)")
    conn.executemany("INSERT INTO raw VALUES (?)", [(v,) for v in cells])

    real_counts = dict(rejected_token_counts(conn, "raw", "debit", resolved_type))
    real_failed = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT debit FROM raw WHERE debit IS NOT NULL "
            f"AND TRY_CAST(debit AS {resolved_type}) IS NULL ORDER BY debit LIMIT 5"
        ).fetchall()
    ]

    quarantine, typing = reconstruct_inputs(tokens, n_rows, resolved_type=resolved_type)
    rig_counts = {e["token"]: e["count"] for e in quarantine["rejected_tokens"]}

    # The reconstruction matches the production loader exactly — same rejected
    # tokens + counts, same truncated failed_examples, same parse_success_rate.
    assert rig_counts == real_counts
    assert quarantine["total_rejected"] == sum(real_counts.values())
    assert typing["failed_examples"] == real_failed
    assert typing["parse_success_rate"] == pytest.approx((n_rows - total_rejected) / n_rows)
