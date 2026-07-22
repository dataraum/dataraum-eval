"""Structural-witness recall — grades the ENGINE's stock/flow classifier as a LIBRARY.

The point this file makes: grading whether the engine decides stock/flow correctly does
NOT need the pipeline. `dataraum.analysis.lineage.reconcile` (DAT-491, ported FROM an eval
probe) is pure arithmetic — no DB, no LLM. We build the `(y, m)` series the witness
consumes straight from the recorded stockflow-events fixture and call the engine's own
`dispose()`. A regression in the engine's reconciliation math is caught in milliseconds,
not a 60-minute e2e run.

This is the deterministic complement to the LLM-claim recall (test_temporal_behavior_e2e,
which IS irreducibly a real-LLM run): the structural witness is the data-grounded
authority, and the authority is checkable here for free.

- y = the measure's level per (series, period); m = the per-period net movement, summed
  from the backing events (probe_events `<col>_delta`) — exactly the anchor the
  aggregation_lineage phase builds.
- A reconciling stock: every entity's Δy == m → the engine confirms CUMULATIVE, all vote.
- A broken stock: the injected per-cell deviation makes the broken series' residual blow
  past the abstain gate → they drop out, so `match_rate` collapses (degrade, not confirm).

If the engine ever MISclassified a reconciling stock as flow, or confirmed a broken one
with full confidence, that is a deterministic engine finding reproduced here — no run.
"""

from __future__ import annotations

from collections import defaultdict

from dataraum.analysis.lineage.models import PATTERN_CUMULATIVE
from dataraum.analysis.lineage.reconcile import dispose

from calibration.unit.fixture import load_fixture, row_records

# Recorded ground truth for detection-stockflow-events-v1 (family seed 20260611).
RECONCILING_STOCKS = ("opening_reserve", "ending_headcount", "debt_level", "outstanding_inventory")
BROKEN_STOCKS = ("outstanding_payables", "payables_balance", "opening_receivables")


def _num(raw: object) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _series_for(
    col: str, probes: list[dict[str, str]], events: list[dict[str, str]]
) -> dict[str, tuple[list[float], list[float]]]:
    """Build the engine witness's per-entity `(y=level, m=movement)` input for one column.

    ``m`` is aggregated from the backing events (``<col>_delta``) per (series, period) —
    independent of ``y`` — exactly as aggregation_lineage would roll it up.
    """
    delta_col = f"{col}_delta"
    movement: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in events:
        d = _num(e.get(delta_col))
        if d is not None:
            movement[e["series_id"]][str(e.get("event_date"))[:7]] += d

    levels: dict[str, dict[str, float]] = defaultdict(dict)
    for r in probes:
        v = _num(r.get(col))
        if v is not None:
            levels[r["series_id"]][r["period"]] = v

    series: dict[str, tuple[list[float], list[float]]] = {}
    for sid, per_level in levels.items():
        periods = sorted(per_level)
        y = [per_level[p] for p in periods]
        m = [movement[sid].get(p, 0.0) for p in periods]
        series[sid] = (y, m)
    return series


def test_engine_witness_confirms_reconciling_and_degrades_broken() -> None:
    conn = load_fixture()
    try:
        probes = row_records(conn, "detection-stockflow-events-v1", "measure_probes")
        events = row_records(conn, "detection-stockflow-events-v1", "probe_events")
    finally:
        conn.close()
    assert probes and events, "stockflow-events probe corpus missing from fixture"

    reconciling = {c: dispose(_series_for(c, probes, events)) for c in RECONCILING_STOCKS}
    broken = {c: dispose(_series_for(c, probes, events)) for c in BROKEN_STOCKS}

    # The engine confirms every genuine stock as CUMULATIVE, with every entity voting.
    for col, verdict in reconciling.items():
        assert verdict is not None, f"engine abstained on a genuine reconciling stock: {col}"
        assert verdict.pattern == PATTERN_CUMULATIVE, f"engine misread reconciling stock {col} as {verdict.pattern}"
        assert verdict.match_rate == 1.0, f"engine not fully confident on clean stock {col}: {verdict.match_rate}"

    # The engine DEGRADES on broken stocks — the broken series abstain, so match_rate
    # collapses. It must not confirm a broken stock with the confidence of a clean one.
    worst_reconciling = min(v.match_rate for v in reconciling.values() if v)
    for col, verdict in broken.items():
        rate = verdict.match_rate if verdict else 0.0
        assert rate < worst_reconciling - 0.1, (
            f"engine did not degrade on broken stock {col}: match_rate {rate} "
            f"vs reconciling {worst_reconciling}"
        )
