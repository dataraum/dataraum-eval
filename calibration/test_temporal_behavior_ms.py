"""Temporal-behaviour (stock vs flow) recall + precision — ms-level, real corpus.

Deterministic proof of the SHIPPED ``measure_temporal_behavior`` on ``data/clean``
(no pipeline, no LLM): the structural reconciliation reads
``trial_balance.debit_balance`` (named like a balance, structurally a per-period
FLOW) as flow and ``balance_sheet.ending_balance`` (a carried-forward level) as
stock — the cases proven in the DAT-459 grounding. Pooled against the ``point_in_time``
concept claim both columns carry (the ``account_balance`` ontology concept), the
flow-claimed-as-balance RAISES conflict (recall) while the genuine stock stays quiet
(precision).

ORDERING grammar (ADR-0009): deltas/orderings, never constant-tuned point thresholds.
This is the ms tier; the pipeline-driven within-run version is the e2e tier.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import pytest
from dataraum.entropy.measurements.temporal_behavior import (
    CLAIM_SPACE,
    measure_temporal_behavior,
    reconciliation_distribution,
)

_DATA = Path(__file__).resolve().parents[1] / "data" / "clean"
_STOCK = CLAIM_SPACE.index("stock")

# The account_balance ontology concept (indicators include debit_balance AND
# ending_balance) declares temporal_behavior point_in_time → a stock claim. Both
# focal columns map to it; the detector derives this from SemanticAnnotation, here
# we supply it directly to isolate the measurement from the LLM.
_STOCK_CLAIM = {"stock": 0.9}
_MARGIN = 0.05  # anti-noise margin on the conflict DELTA, not a detection threshold


def _period_key(p: str) -> tuple[int, int]:
    y, m = p.split("-")[:2]
    return int(y), int(m)


def _gl_anchors() -> dict[tuple[str, str], dict[str, float]]:
    """Per-(account, period) gross_debit / gross_credit / net from posted GL lines."""
    entries: dict[str, tuple[str, str]] = {}
    with open(_DATA / "journal_entries.csv", newline="") as f:
        for r in csv.DictReader(f):
            entries[r["entry_id"]] = (r["date"][:7], r.get("status", "").lower())
    agg: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    with open(_DATA / "journal_lines.csv", newline="") as f:
        for r in csv.DictReader(f):
            info = entries.get(r["entry_id"])
            if info is None or info[1] != "posted":
                continue
            key = (r["account_id"], info[0])
            agg[key][0] += float(r["debit"] or 0.0)
            agg[key][1] += float(r["credit"] or 0.0)
    return {
        k: {"gross_debit": gd, "gross_credit": gc, "net": gd - gc}
        for k, (gd, gc) in agg.items()
    }


def _series(
    focal_file: str, value_col: str, anchors: dict[tuple[str, str], dict[str, float]]
) -> dict[str, dict[str, list]]:
    """Per-account ``{"values", "anchors": [net, gross_debit, gross_credit]}``."""
    rows: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with open(_DATA / focal_file, newline="") as f:
        for r in csv.DictReader(f):
            v = r.get(value_col)
            if v in (None, ""):
                continue
            rows[r["account_id"]].append((r["period"], float(v)))
    series: dict[str, dict[str, list]] = {}
    for acct, pairs in rows.items():
        pairs.sort(key=lambda pv: _period_key(pv[0]))
        net, gd, gc = [], [], []
        for period, _ in pairs:
            a = anchors.get((acct, period), {"gross_debit": 0.0, "gross_credit": 0.0, "net": 0.0})
            net.append(a["net"])
            gd.append(a["gross_debit"])
            gc.append(a["gross_credit"])
        series[acct] = {"values": [v for _, v in pairs], "anchors": [net, gd, gc]}
    return series


@pytest.fixture(scope="module")
def anchors() -> dict[tuple[str, str], dict[str, float]]:
    if not (_DATA / "balance_sheet.csv").exists():
        pytest.skip("data/clean not generated with balance_sheet — run scripts/regen_data.py clean")
    return _gl_anchors()


# --- structural reconciliation (the grounded core, no claim) ------------------
def test_trial_balance_debit_reconciles_as_flow(anchors) -> None:
    dist = reconciliation_distribution(_series("trial_balance.csv", "debit_balance", anchors))
    assert dist["flow"] > 0.8


def test_balance_sheet_ending_reconciles_as_stock(anchors) -> None:
    dist = reconciliation_distribution(_series("balance_sheet.csv", "ending_balance", anchors))
    assert dist["stock"] > 0.8


# --- pooled recall / precision (vs the point_in_time claim) -------------------
def test_recall_flow_named_balance_raises_conflict(anchors) -> None:
    """trial_balance.debit_balance: claim stock, data flow → conflict over the quiet stock."""
    recall = measure_temporal_behavior(
        "trial_balance", "debit_balance", _series("trial_balance.csv", "debit_balance", anchors), _STOCK_CLAIM
    )
    precision = measure_temporal_behavior(
        "balance_sheet", "ending_balance", _series("balance_sheet.csv", "ending_balance", anchors), _STOCK_CLAIM
    )
    assert recall.result.conflict > precision.result.conflict + _MARGIN


def test_precision_genuine_stock_stays_quiet(anchors) -> None:
    """balance_sheet.ending_balance: claim stock, data stock → agree, low conflict."""
    adj = measure_temporal_behavior(
        "balance_sheet", "ending_balance", _series("balance_sheet.csv", "ending_balance", anchors), _STOCK_CLAIM
    )
    assert adj.result.conflict < 0.2
    assert adj.result.posterior[_STOCK] > 0.5
