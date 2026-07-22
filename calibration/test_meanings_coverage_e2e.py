"""Meaning-coverage parity oracle (DAT-853, for the DAT-823 W3-F semantic-authoring split).

Semantic authoring moves into the engine split; this oracle asserts the split does not
REGRESS meaning coverage below the clean-corpus baseline — every eligible catalogue column
carries a ``ColumnConcept`` row with a non-empty ``meaning`` (the ticket's 62/62 on the clean
finance corpus = full coverage). Graded from DB rows + the NEW ``meaning_status`` column
(NULL on pre-split rows, ``'determined'``/``'ambiguous'`` post-split): ``'ambiguous'`` COUNTS
as covered — it is declared ignorance WITH a meaning present; a MISSING concept row or an
empty meaning is the failure.

Forward-looking, oracle-first (ADR-0022, like the P2 grounding oracles): the oracle probes for
the ``meaning_status`` surface and SKIPS until the split lands, and stands down on a Tier-B
(wild) corpus, which authors no concepts. The pure grader (:func:`grade_meaning_coverage`) is
pinned in Tier-1 (``calibration/unit/test_meanings_coverage.py``) over synthetic rows.

Tier-3 (docker + Temporal + LLM upstream): marked ``llm``; pytest auto-collects.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import (
    is_wild,
    meaning_status_present,
    read_meaning_coverage,
)
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="begin_session")


@dataclass(frozen=True)
class MeaningCoverage:
    """The coverage verdict over the eligible columns."""

    covered: list[str]
    uncovered: dict[str, str]  # column -> failure reason
    by_status: dict[str, int]  # meaning_status label -> covered count (reporting)

    @property
    def is_full(self) -> bool:
        return not self.uncovered


def grade_meaning_coverage(rows: Iterable[Any]) -> MeaningCoverage:
    """Grade meaning coverage over eligible columns (pure; Tier-1-able).

    Covered = a ColumnConcept row exists AND its meaning is non-empty. ``meaning_status`` is
    informational for the covered set: ``'determined'``, ``'ambiguous'``, and NULL (pre-split
    rows) all COUNT as covered when a meaning is present — ``'ambiguous'`` is declared
    ignorance WITH a meaning, not a gap. Uncovered (the failure) = no concept row, or a
    NULL/blank meaning. Each row carries ``column`` / ``has_concept`` / ``meaning`` /
    ``meaning_status`` (duck-typed so synthetic rows exercise the split without a pipeline).
    """
    covered: list[str] = []
    uncovered: dict[str, str] = {}
    by_status: Counter[str] = Counter()
    for r in rows:
        if not r.has_concept:
            uncovered[r.column] = "no ColumnConcept row"
            continue
        if not (r.meaning and r.meaning.strip()):
            uncovered[r.column] = "empty meaning"
            continue
        covered.append(r.column)
        by_status[r.meaning_status or "null"] += 1
    return MeaningCoverage(
        covered=sorted(covered),
        uncovered=dict(sorted(uncovered.items())),
        by_status=dict(by_status),
    )


@pytest.mark.llm
def test_every_eligible_column_carries_a_meaning(
    metadata_truth: dict[str, Any], strategy_name: str
) -> None:
    """Every eligible catalogue column has a ColumnConcept row with a non-empty meaning.

    The post-split coverage-parity assertion: a missing row or an empty meaning is a
    regression; ``'ambiguous'`` still counts. Skips until ``meaning_status`` lands
    (oracle-first) and on a Tier-B corpus (no authored concepts).
    """
    require_pipeline_run(strategy_name)
    if is_wild(metadata_truth):
        pytest.skip("Tier-B corpus authors no concept meanings — structural truth only")

    with workspace_session() as session:
        if not meaning_status_present(session):
            pytest.skip(
                "meaning_status column absent — the DAT-823 semantic-authoring split (W3-F) "
                "has not landed; the coverage-parity oracle activates post-split (oracle-first)"
            )
        rows = read_meaning_coverage(session)

    assert rows, "no eligible columns read — the catalogue is empty (a stop-condition)"
    coverage = grade_meaning_coverage(rows)
    print(
        f"\n[meaning coverage] {len(coverage.covered)}/{len(rows)} eligible columns carry a "
        f"meaning on {strategy_name}; by status {coverage.by_status}"
    )
    for col, reason in coverage.uncovered.items():
        print(f"  UNCOVERED: {col} — {reason}")

    assert coverage.is_full, (
        "eligible columns carry no authored meaning — a post-split coverage regression (a "
        "missing ColumnConcept row or an empty meaning; an 'ambiguous' status would still "
        "count):\n" + "\n".join(f"  {c}: {reason}" for c, reason in coverage.uncovered.items())
    )
