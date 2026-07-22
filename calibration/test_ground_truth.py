"""Ground truth metrics — do computed values match known answers?

Two things, both **without a pipeline run** (no docker, no Temporal, no LLM):

1. ``ground_truth.yaml`` is well-formed and its documented invariants hold.
2. The golden SQL, run offline over the generated CSVs (``outcomes.label(offline=True)``),
   reproduces those known metrics on CLEAN data. This is the financial-accuracy
   check that previously ran only inside a paid live run — it needs generated data,
   not the assembled pipeline, so it belongs in the free lane.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import outcomes


def test_ground_truth_loaded(ground_truth: dict[str, Any]) -> None:
    """Verify ground_truth.yaml has expected structure."""
    assert "annual" in ground_truth
    assert "invariants" in ground_truth
    assert "monthly" in ground_truth

    annual = ground_truth["annual"]
    assert "total_revenue" in annual
    assert "total_expenses" in annual
    assert "free_cash_flow" in annual


def test_invariants_hold(ground_truth: dict[str, Any]) -> None:
    """Pre-injection data invariants should be documented."""
    inv = ground_truth["invariants"]
    assert inv["journal_balanced"] is True
    assert inv["trial_balance_balanced"] is True
    assert inv["invoice_payment_matched"] is True


def test_offline_metrics_reproduce_ground_truth(
    strategy_name: str, ground_truth: dict[str, Any]
) -> None:
    """Golden SQL over the generated CSVs reproduces the known metrics — no pipeline.

    ``outcomes.label(offline=True)`` computes every deliverable metric straight from
    the generated CSVs via DuckDB and scores each against ``ground_truth.yaml`` under
    the deliverable spec's tolerance. On CLEAN data this MUST reproduce ground truth —
    a miss is a real defect in the generator, the golden SQL, or the committed truth.
    On an injected strategy the deviations ARE the injection, so we report and stand
    down: this is the only place the financial check runs for free (the lake-mode
    buckets and prevention attribution still need the paid run).
    """
    result = outcomes.label(strategy_name, offline=True)
    annual = ground_truth.get("annual", {})
    scored = [m for m in result["metrics"] if "in_tolerance" in m]
    gaps = [m for m in result["metrics"] if "skipped" in m]

    print(f"\n[offline metrics] strategy={strategy_name} "
          f"({len(scored)} scored, {len(gaps)} not computed):")
    for m in scored:
        flag = "ok " if m["in_tolerance"] else "OFF"
        print(f"  [{flag}] {m['metric']:<22} computed={m['computed']} "
              f"expected={m['expected']} dev={m['deviation']}")
    for m in gaps:
        print(f"  [ -- ] {m['metric']:<22} {m['skipped']}")

    assert scored, "offline labeler computed no scorable metric — generator/spec drift"

    # The labeler's per-metric expected values come from this same ground_truth.yaml;
    # confirm they agree, so a labeler reading a stale/wrong truth file is caught here
    # regardless of strategy.
    for m in scored:
        if m["metric"] in annual:
            assert float(m["expected"]) == float(annual[m["metric"]]), (
                f"{m['metric']}: labeler expected {m['expected']} but ground_truth.yaml "
                f"annual says {annual[m['metric']]}"
            )

    if strategy_name != "clean":
        pytest.skip(
            f"offline metric reproduction is a clean-data invariant; on injected "
            f"'{strategy_name}' the deviations above are the injection, reported not graded"
        )

    off = [m for m in scored if not m["in_tolerance"]]
    assert not off, (
        "offline golden SQL does not reproduce ground_truth on CLEAN data — a defect in "
        "the generator, the golden SQL, or the committed ground truth:\n  "
        + "\n  ".join(
            f"{m['metric']}: computed {m['computed']} vs expected {m['expected']} "
            f"(dev {m['deviation']})"
            for m in off
        )
    )
