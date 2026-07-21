"""Tier-1 — the bus-matrix conform summary over synthetic cells (DAT-853).

Pins :func:`grade_bus_matrix_conform` in milliseconds without a pipeline. A cross-fact fold
carrying a ``conformed_group`` is NOT a collapse; a cross-fact fold with every cell abstained
(no ``conformed_group``) IS the all-abstained collapse; and the legitimate no-conform shapes —
a single-fact fold, different-dimension folds, a referenced-only run — must NEVER read as a
collapse (the false-positive guards).
"""

from __future__ import annotations

from types import SimpleNamespace

from calibration.test_bus_matrix_conform_e2e import grade_bus_matrix_conform


def _cell(
    fact: str,
    *,
    attachment: str = "folded",
    roles: tuple[str, ...] = ("customer_id",),
    conformed_group: str | None = None,
    needs_confirmation: bool = False,
) -> SimpleNamespace:
    """A stand-in for a persisted bus-matrix cell (attribute access, like a SQLAlchemy Row)."""
    return SimpleNamespace(
        fact=fact,
        attachment=attachment,
        roles=list(roles),
        conformed_group=conformed_group,
        needs_confirmation=needs_confirmation,
    )


def test_cross_fact_fold_conformed_is_not_a_collapse() -> None:
    """Two facts fold the same key and the judge conformed them — a healthy verdict."""
    cells = [
        _cell("orders", conformed_group="g1"),
        _cell("shipments", conformed_group="g1"),
    ]
    summary = grade_bus_matrix_conform(cells)
    assert summary.cross_fact_keys == 1
    assert summary.conformed == 2
    assert not summary.collapsed


def test_cross_fact_fold_all_abstained_is_a_collapse() -> None:
    """The failure signature: cross-fact folds exist but every cell abstained to needs_confirmation."""
    cells = [
        _cell("orders", conformed_group=None, needs_confirmation=True),
        _cell("shipments", conformed_group=None, needs_confirmation=True),
    ]
    summary = grade_bus_matrix_conform(cells)
    assert summary.cross_fact_keys == 1
    assert summary.conformed == 0
    assert summary.needs_confirmation == 2
    assert summary.collapsed


def test_single_fact_fold_is_not_a_collapse() -> None:
    """One fact carries the fold — no cross-fact identity to conform, so no collapse."""
    summary = grade_bus_matrix_conform(
        [_cell("orders", conformed_group=None, needs_confirmation=True)]
    )
    assert summary.cross_fact_keys == 0
    assert not summary.collapsed


def test_different_dimension_folds_are_not_a_collapse() -> None:
    """Two facts fold DIFFERENT dimensions — no shared fold key, nothing to conform across."""
    cells = [
        _cell("orders", roles=("customer_id",), conformed_group=None, needs_confirmation=True),
        _cell("shipments", roles=("warehouse_id",), conformed_group=None, needs_confirmation=True),
    ]
    summary = grade_bus_matrix_conform(cells)
    assert summary.cross_fact_keys == 0
    assert not summary.collapsed


def test_referenced_only_run_is_not_a_collapse() -> None:
    """A run with only referenced cells has no folded conform surface at all."""
    summary = grade_bus_matrix_conform(
        [_cell("orders", attachment="referenced", roles=("region_id",))]
    )
    assert summary.folded == 0
    assert summary.cross_fact_keys == 0
    assert not summary.collapsed
