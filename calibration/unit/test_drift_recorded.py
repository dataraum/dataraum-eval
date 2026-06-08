"""Tier-2 FINDING: why temporal_drift was cut (DAT-442 reset).

The question that cost several 10-minute pipeline runs — on a naturally-volatile
column, does a distribution-drift statistic separate an injected 1.35× shift from
the column's own month-to-month noise? — answered here in <1 s on the frozen real
values. The answer is NO: the clean data is non-stationary by design
(`month-end-close`), so drift ≈ noise on flows, and no statistic separates them.
That is the evidence the temporal_drift detector was removed (real drift → DAT-445's
expected-variation model). The KS change-statistic is computed inline here so the
finding stands independent of the (now-cut) engine code.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from scipy.stats import ks_2samp  # type: ignore[import-untyped]

from calibration.unit.fixture import load_fixture, period_values

_FLOW_COLUMNS = [("bank_transactions", "amount"), ("invoices", "amount"), ("payments", "amount")]
_SEPARATION_MARGIN = 0.05  # what "measurably above natural volatility" would require
_MIN_SAMPLE = 20


def _ks_change_drift(periods: list[list[float]]) -> float:
    """Max two-sample KS across period-boundary splits — the standard distribution-
    drift / change-detection statistic. The grounded measure, self-contained."""
    usable = [p for p in periods if len(p) >= _MIN_SAMPLE]
    if len(usable) < 2:
        return 0.0
    best = 0.0
    for k in range(1, len(usable)):
        before = [v for p in usable[:k] for v in p]
        after = [v for p in usable[k:] for v in p]
        if before and after:
            best = max(best, float(ks_2samp(before, after).statistic))
    return best


@pytest.fixture(scope="module")
def fixture() -> Iterator[sqlite3.Connection]:
    conn = load_fixture()
    yield conn
    conn.close()


def _drift(fixture: sqlite3.Connection, strategy: str, source: str, col: str) -> float:
    return _ks_change_drift(period_values(fixture, strategy, source, col, "date"))


def test_finding_drift_does_not_separate_on_flows(fixture: sqlite3.Connection) -> None:
    """Recorded finding: injected does NOT clear clean + margin on any flow column.

    Passes while the finding holds. If a future drift framing (e.g. departure from
    an expected-variation baseline, DAT-445) makes a flow separate, this test flips
    — the signal to reconsider drift's place.
    """
    for source, col in _FLOW_COLUMNS:
        clean = _drift(fixture, "clean", source, col)
        injected = _drift(fixture, "detection-v1", source, col)
        print(f"{source}.{col}  clean={clean:.3f}  injected={injected:.3f}  Δ={injected - clean:+.3f}")
        assert injected <= clean + _SEPARATION_MARGIN, (
            f"{source}.{col} now separates (Δ={injected - clean:+.3f}) — drift may be "
            "meaningful here; reconsider (DAT-445)."
        )
