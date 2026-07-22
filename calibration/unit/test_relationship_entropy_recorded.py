"""Relationship grounding net (Phase 4) — the cheap backbone net for `relationship_entropy`.

`relationship_entropy` measures how reliable a discovered join is. The grounded
structural statistic behind it is the **orphan rate**: the fraction of child rows
whose foreign key has no matching parent key (a referential-integrity violation).
Recall is ordering (charter): injected > clean + margin, never a point threshold.

The graded relationship is `payments.invoice_id → invoices.invoice_id`. On clean data
referential integrity holds — every payment resolves to an invoice, orphan rate 0.
`break_referential_integrity` (ratio 0.20) rewrites 20% of the child keys to danglers,
driving the orphan rate to exactly that. The net uses the FK columns the capture now
retains (`_FK_COLUMNS`); it does not reimplement the engine's join discovery.

- Tier 1: the statistic is 0 on an intact child/parent pair and rises with orphans.
- Tier 2: over the recorded fixture, clean orphans 0%, the injected child orphans more.

If the recorded leg had NOT separated, that is a finding (like the outlier_rate CUT),
filed, never a relaxed assertion. It separates by the full injection ratio.
"""

from __future__ import annotations

from calibration.unit.fixture import load_fixture, row_records


def orphan_rate(
    child: list[dict[str, str]], parent: list[dict[str, str]], fk_col: str, key_col: str
) -> float:
    """Fraction of ``child`` rows whose ``fk_col`` has no match in ``parent[key_col]``.

    The standard referential-integrity violation (orphan) rate. Child rows with a
    missing/blank FK are skipped (no key to resolve). Returns 0.0 when no child row
    carries an FK.
    """
    parent_keys = {r.get(key_col) for r in parent if r.get(key_col) not in (None, "")}
    fks = [r.get(fk_col) for r in child if r.get(fk_col) not in (None, "")]
    if not fks:
        return 0.0
    orphans = sum(1 for v in fks if v not in parent_keys)
    return orphans / len(fks)


def test_orphan_rate_separates_synthetic() -> None:
    parent = [{"id": f"P{i}"} for i in range(100)]
    intact = [{"fk": f"P{i % 100}"} for i in range(200)]  # every child resolves
    broken = [{"fk": "MISSING" if i % 4 == 0 else f"P{i % 100}"} for i in range(200)]
    assert orphan_rate(intact, parent, "fk", "id") == 0.0
    assert orphan_rate(broken, parent, "fk", "id") == 0.25  # every 4th child orphaned


def test_relationship_injection_separates_from_clean_recorded() -> None:
    # break_referential_integrity dangles 20% of payments.invoice_id; the orphan rate
    # against invoices.invoice_id must exceed the clean twin's (ordering, not a threshold).
    conn = load_fixture()
    try:
        clean = orphan_rate(
            row_records(conn, "clean", "payments"),
            row_records(conn, "clean", "invoices"),
            "invoice_id",
            "invoice_id",
        )
        injected = orphan_rate(
            row_records(conn, "detection-v1", "payments"),
            row_records(conn, "detection-v1", "invoices"),
            "invoice_id",
            "invoice_id",
        )
    finally:
        conn.close()
    # Clean referential integrity is what grounds the relationship as real.
    assert clean == 0.0, f"referential integrity does not hold on clean: orphan rate {clean:.4f}"
    assert injected > clean + 0.05, f"orphan injection did not separate: injected={injected:.4f} clean={clean:.4f}"
