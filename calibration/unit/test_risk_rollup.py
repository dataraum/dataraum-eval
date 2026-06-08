"""TABLE 2 of the two-table model — the loss table.

    risk(column, intent) = clamp01( Σ_measurement  weight[measurement, intent] · value )

That clamped dot-product over loss.yaml IS the whole rollup — no noisy-OR graph, no
invented edge weights, no intent-word nodes. Bands come from loss.yaml's
``readiness_bands``. This proves the second table end-to-end, in milliseconds, with
the network path entirely uninvolved (null_ratio has no network node).
"""

from __future__ import annotations

import pytest
from dataraum.entropy.loss import LossConfig, get_loss_config
from dataraum.entropy.stats import null_ratio

from calibration.unit.fixture import column_cells, load_fixture


def _risk(values: dict[str, float], intent: str, cfg: LossConfig) -> float:
    """The loss-table dot-product for one column's measurement values, one intent.

    Mirrors ``loss.loss_risk_for_object`` for a single-signal (raw-rate) measurement:
    the value is multiplied by each per-intent weight and summed, then clamped.
    """
    total = 0.0
    for measurement_id, value in values.items():
        weights = cfg.measurements.get(measurement_id, {}).get(intent, {})
        total += sum(w * value for w in weights.values())
    return min(1.0, max(0.0, total))


def test_loss_table_is_a_clamped_dot_product_with_honest_bands() -> None:
    """Arithmetic oracle, no fixture: null_ratio's aggregation weight is 0.7, so a
    0.40 missing fraction is 0.28 risk (ready); 0.50 is 0.35 (investigate)."""
    cfg = get_loss_config()
    assert _risk({"null_ratio": 0.40}, "aggregation_intent", cfg) == pytest.approx(0.28)
    assert cfg.band(_risk({"null_ratio": 0.40}, "aggregation_intent", cfg)) == "ready"
    assert cfg.band(_risk({"null_ratio": 0.50}, "aggregation_intent", cfg)) == "investigate"


def test_loss_table_separates_injected_from_clean_on_the_fixture() -> None:
    """value → loss → band end-to-end on recorded data: the cost_center null
    injection moves query readiness across the ready→investigate boundary."""
    cfg = get_loss_config()
    conn = load_fixture()
    clean = null_ratio(column_cells(conn, "clean", "journal_lines", "cost_center"))
    injected = null_ratio(column_cells(conn, "detection-v1", "journal_lines", "cost_center"))

    # query weight 0.5: clean 0.519·0.5 = 0.26 (ready); injected 0.710·0.5 = 0.36 (investigate).
    assert cfg.band(_risk({"null_ratio": clean}, "query_intent", cfg)) == "ready"
    assert cfg.band(_risk({"null_ratio": injected}, "query_intent", cfg)) == "investigate"
