"""Temporal-behavior grounding net (Phase 4) — the cheap backbone net for `temporal_behavior`.

temporal_behavior adjudicates whether a measure column is a STOCK (a carried-forward
level — must not be summed across periods) or a FLOW (a per-period movement — additive).
This is NOT an LLM decision: the authority is the data-grounded STRUCTURAL reconciliation
witness (DAT-491). The `llm_claim` witness is one vote in the pool; the deterministic
trajectory-shape classifier was CUT (DAT-459), and the ontology_prior was dropped
(DAT-657) — so what actually decides stock/flow is arithmetic.

The grounded statistic is the **stock reconciliation break rate**: a genuine stock's
per-period delta (level[t] − level[t−1]) equals the sum of its backing movement events
in that (series, period) cell (opening + Σ events = closing). A reconciling stock holds
that identity on every cell; a broken one (the injected `reconciles: false` strata) does
not. Recall is ordering (charter): broken > reconciling + margin, never a point threshold.

Grounded on detection-stockflow-events-v1 (measure_probes ⋈ probe_events on series_id):
- reconciling stocks reconcile on 0% of non-opening cells (residual exactly 0.00),
- broken stocks break on 60–87% of them (residual 121–196).

The stock/flow labels below are the recorded ground truth for the fixed family seed
(20260611 in the strategy); the events column for stock C is always `<C>_delta`. If the
identity had NOT separated reconciling from broken, that is a finding, never a relaxed
assertion. It separates by the full break_ratio.

- Tier 1: the reconciliation is 0 when events sum to the deltas, > 0 when they are off.
- Tier 2: over the recorded fixture, reconciling stocks hold it, broken stocks do not.
"""

from __future__ import annotations

from collections import defaultdict

from calibration.unit.fixture import load_fixture, row_records

# Recorded ground truth for the detection-stockflow-events-v1 family (seed 20260611).
# Backed stock columns split by their `reconciles` label; events column is `<col>_delta`.
RECONCILING_STOCKS = ("opening_reserve", "ending_headcount", "debt_level", "outstanding_inventory")
BROKEN_STOCKS = ("outstanding_payables", "payables_balance", "opening_receivables")
RECONCILE_TOL = 0.02  # 2 cents — float slack, far below any injected deviation


def _num(raw: object) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def stock_reconciliation_break_rate(
    probes: list[dict[str, str]],
    events: list[dict[str, str]],
    level_col: str,
    delta_col: str,
) -> float:
    """Fraction of non-opening (series, period) cells where the stock delta != Σ events.

    ``probes`` carries the level per (series_id, period); ``events`` carries per-event
    movements (``delta_col``) dated inside a period. For each series, the first period is
    skipped (its opening level is not recorded, so the delta is unknowable). Returns 0.0
    when no cell is evaluable.
    """
    esum: dict[tuple[str, str], float] = defaultdict(float)
    for e in events:
        d = _num(e.get(delta_col))
        if d is not None:
            esum[(e["series_id"], str(e.get("event_date", ""))[:7])] += d

    by_series: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in probes:
        lvl = _num(r.get(level_col))
        if lvl is not None:
            by_series[r["series_id"]].append((r["period"], lvl))

    total = broken = 0
    for sid, seq in by_series.items():
        seq.sort(key=lambda x: x[0])
        for i in range(1, len(seq)):  # skip the opening period
            period, lvl = seq[i]
            delta = lvl - seq[i - 1][1]
            total += 1
            if abs(delta - esum.get((sid, period), 0.0)) > RECONCILE_TOL:
                broken += 1
    return broken / total if total else 0.0


def test_stock_reconciliation_separates_synthetic() -> None:
    # Two periods per series; events either sum to the delta (reconciling) or are off.
    probes = [
        {"series_id": "S0", "period": "2025-01", "lvl": "1000"},
        {"series_id": "S0", "period": "2025-02", "lvl": "1200"},  # delta +200
    ]
    good = [{"series_id": "S0", "event_date": "2025-02-10", "mv": "200"}]  # sums to +200
    bad = [{"series_id": "S0", "event_date": "2025-02-10", "mv": "50"}]  # off by 150
    assert stock_reconciliation_break_rate(probes, good, "lvl", "mv") == 0.0
    assert stock_reconciliation_break_rate(probes, bad, "lvl", "mv") == 1.0


def test_temporal_behavior_reconciliation_separates_recorded() -> None:
    conn = load_fixture()
    try:
        probes = row_records(conn, "detection-stockflow-events-v1", "measure_probes")
        events = row_records(conn, "detection-stockflow-events-v1", "probe_events")
    finally:
        conn.close()
    assert probes and events, "stockflow probe corpus missing from fixture"

    def rate(col: str) -> float:
        return stock_reconciliation_break_rate(probes, events, col, f"{col}_delta")

    reconciling = {c: rate(c) for c in RECONCILING_STOCKS}
    broken = {c: rate(c) for c in BROKEN_STOCKS}

    # A genuine (reconciling) stock holds the identity on EVERY non-opening cell — that
    # exact 0 is what grounds the reconciliation as the structural authority.
    worst_reconciling = max(reconciling.values())
    assert worst_reconciling == 0.0, f"a reconciling stock did not reconcile: {reconciling}"
    # Every broken stock breaks it on a real fraction of cells; the weakest break still
    # clears the reconciling group by a wide margin (ordering, not a tuned threshold).
    weakest_broken = min(broken.values())
    assert weakest_broken > worst_reconciling + 0.10, f"break did not separate: broken={broken} reconciling={reconciling}"
