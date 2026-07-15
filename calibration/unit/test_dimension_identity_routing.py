"""DAT-762 lane acceptance, component 1: routing safety + recall (Tier-1).

Runs the ENGINE's deterministic class routing over the frozen 45-cell
DAT-757 scorecard fixture (dimension_identity_cells.json) and asserts the
lane's safety property, measured by the scorecard (DAT-757 comment 16302):

- ZERO LEAKAGE (hard): no cell of the stats-owned classes — the 27/27 the
  LLM channels systematically destroy (every dirty-true hierarchy and
  weak-true org edge REJECTed by both judge channels) — is ever routed to
  the veto judge. A leak here means the lane can delete real metadata the
  statistics had proven.
- FULL RECALL (hard): every veto-class cell (quasi-identifier, free-text
  determinant, proxy bijection) the stack ASSERTS (C1 MERGE/HIERARCHY) is
  routed to its class — these are the measured names-judgeable errors the
  lane exists to fix (C2 4/4 on quasi-identifiers vs C1 0/4).

Routing consumes VALUE evidence only (counts, dtypes, raw sample values);
shape features are computed through the engine's own code so the feature
definitions have exactly one home. Skips until the installed engine carries
the router (pre-DAT-762-merge mains).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

routing = pytest.importorskip(
    "dataraum.analysis.hierarchies.routing",
    reason="engine has no dimension-identity routing yet (pre-DAT-762)",
)

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures/dimension_identity_cells.json"

# The veto-eligible classes and their expected routing (DAT-757 scorecard).
_VETO_CLASS = {
    "D-quasi-identifier": "quasi-identifier",
    "E-free-text": "free-text-determinant",
    "P-proxy-bijection": "proxy-bijection",
}
# The stats-owned single-view classes: routed = the lane may destroy them.
_PROTECTED = {
    "A-true-alias",
    "B-dirty-alias",
    "F-dirty-hierarchy",
    "H-weak-true",
    "I-vacuous-skew",
    "J-true-fk",
    "M-measure-derived",
}


def _cells() -> list[dict[str, Any]]:
    return json.loads(_FIXTURE.read_text())["cells"]


def _evidence(col: dict[str, Any]) -> Any:
    return routing.ColumnEvidence(
        n_rows=col["n_rows"],
        n_distinct=col["n_distinct"],
        dtype=col["dtype"],
        sample_values=col["sample_distinct_values"],
    )


def _route(cell: dict[str, Any]) -> str | None:
    """Route one asserted cell through the engine's router, arm by C1 verdict."""
    a, b = _evidence(cell["col_a"]), _evidence(cell["col_b"])
    if cell["c1_verdict"] == "MERGE":
        return routing.route_alias(a, b)
    return routing.route_edge(a, b)


def _asserted(cell: dict[str, Any]) -> bool:
    # The router only ever sees structures the stack asserted; REJECT/ROLE
    # cells never reach it (ROLE rows are the #494 role_verdict machinery).
    return (
        cell.get("c1_verdict") in ("MERGE", "HIERARCHY")
        and "col_a" in cell
        and "col_b" in cell
    )


def test_zero_leakage_into_stats_owned_classes() -> None:
    """No protected cell is ever shown to the veto judge (the 27/27 guard)."""
    leaks = [
        f"{c['id']} ({c['klass']}): routed {_route(c)!r}"
        for c in _cells()
        if c["klass"] in _PROTECTED and _asserted(c) and _route(c) is not None
    ]
    assert not leaks, (
        "routing forwarded stats-owned structures to the veto judge — the judge "
        "is MEASURED to destroy these classes (DAT-757 scorecard):\n  "
        + "\n  ".join(leaks)
    )


def test_full_recall_on_veto_classes() -> None:
    """Every asserted veto-class cell is routed to its measured class."""
    misses = [
        f"{c['id']} ({c['klass']}): routed {_route(c)!r}, want {_VETO_CLASS[c['klass']]!r}"
        for c in _cells()
        if c["klass"] in _VETO_CLASS and _asserted(c) and _route(c) != _VETO_CLASS[c["klass"]]
    ]
    assert not misses, (
        "asserted veto-class structures not routed — the measured C1 errors the "
        "lane exists to fix stay unjudged:\n  " + "\n  ".join(misses)
    )


def test_role_cells_stay_unrouted() -> None:
    """C (roles) belongs to the #494 role_verdict machinery, never the veto."""
    wrong = [
        f"{c['id']} ({c['klass']}): routed {_route(c)!r}"
        for c in _cells()
        if c["klass"] == "C-role" and _asserted(c) and _route(c) is not None
    ]
    assert not wrong, (
        "role cells routed to the veto — roles are the #494 role_verdict "
        "machinery:\n  " + "\n  ".join(wrong)
    )


def test_grain_cells_route_per_measured_truth() -> None:
    """G (grain) cells: id-shaped grain keys stay with the stats; the temporal
    proxy determinant routes — its pre-registered truth is REJECT ("a timestamp
    is a proxy determinant, not a grouping key") and the names-judge REJECTs it
    in both scorecard repetitions, so routing G3 FIXES a measured C1 error
    (composite 43/45 > the scorecard's class-routed ≈42)."""
    expected = {"G1": None, "G2": None, "G3": "quasi-identifier"}
    got = {c["id"]: _route(c) for c in _cells() if c["klass"] == "G-grain" and _asserted(c)}
    assert got == expected, f"grain routing diverged from measured truth: {got}"
