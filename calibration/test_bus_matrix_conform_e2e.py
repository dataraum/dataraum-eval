"""Bus-matrix conform/abstain non-regression (DAT-853).

Post-split (DAT-823 W3-F) the ``dimension_hierarchies`` conform judges read later-authored
meanings; this oracle catches a meaning-starved judge collapsing to abstention. Structural and
truth-free: when the run produced folded bus-matrix cells whose fold key spans >= 2 facts
(cross-fact identity the conform judge should adjudicate), at least one folded cell must carry
a ``conformed_group``. The failure signature is the ALL-ABSTAINED collapse — every folded cell
left ``needs_confirmation`` with no ``conformed_group``.

Counts only, no thresholds. The per-fold truth grading (which fold, which label, which key)
lives in ``test_bus_matrix_e2e`` / ``test_folded_dims_e2e``; this is the wholesale
"did conform produce ANY verdict when it had cross-fact folds to work on" non-regression
surface, which those truth-scoped tests do not assert. The pure grader
(:func:`grade_bus_matrix_conform`) is pinned in Tier-1
(``calibration/unit/test_bus_matrix_conform.py``) over synthetic cells.

Tier-3 (docker + Temporal + LLM upstream): marked ``llm``; pytest auto-collects.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import is_wild, read_view_exists
from calibration.tools._runs import short, workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="begin_session")


@dataclass(frozen=True)
class ConformSummary:
    """The conform pass's structural outcome over persisted bus-matrix cells."""

    total: int
    folded: int
    cross_fact_keys: int  # fold keys (role sets) carried on >= 2 facts
    conformed: int  # folded cells with a non-null conformed_group
    needs_confirmation: int
    collapsed: bool  # cross-fact identity exists but ZERO conformed => all-abstained


def grade_bus_matrix_conform(cells: Iterable[Any]) -> ConformSummary:
    """Summarize the conform pass over persisted bus-matrix cells (pure; Tier-1-able).

    Each cell carries ``attachment`` (``'folded'``/``'referenced'``), a ``roles`` fold-key
    list, a nullable ``conformed_group`` (the judge's cross-fact identity key, DAT-800), and a
    ``needs_confirmation`` flag. Cross-fact identity exists where a fold key appears on >= 2
    facts — reusing the >= 2-facts threshold ``test_bus_matrix_e2e`` gates conformity on
    (grouping here by the engine's own ``roles`` set, since this surface is truth-free rather
    than keyed on the declared fold column), so the gate is the codebase's established
    semantics, not a tuned threshold. ``collapsed`` is the all-abstained signature: cross-fact
    keys exist yet no folded cell was conformed.
    """
    cells = list(cells)
    folded = [c for c in cells if c.attachment == "folded"]
    facts_by_key: dict[frozenset[str], set[str]] = {}
    for c in folded:
        facts_by_key.setdefault(frozenset(c.roles), set()).add(c.fact)
    cross_fact = {key for key, facts in facts_by_key.items() if len(facts) >= 2}
    conformed = [c for c in folded if c.conformed_group is not None]
    needs = [c for c in folded if c.needs_confirmation]
    return ConformSummary(
        total=len(cells),
        folded=len(folded),
        cross_fact_keys=len(cross_fact),
        conformed=len(conformed),
        needs_confirmation=len(needs),
        collapsed=bool(cross_fact) and not conformed,
    )


def _read_conform_cells(strategy_name: str) -> list[Any] | None:
    """Persisted bus-matrix cells for the conform summary, or None when the view is absent.

    None means ``current_bus_matrix`` is not present (a run predating the DAT-762 engine
    build) — the caller skips. Mirrors ``test_bus_matrix_e2e.engine_cells``: the promoted-run
    view via the read schema, ``short``-narrowed fact names.
    """
    from types import SimpleNamespace

    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    with workspace_session() as session:
        if not read_view_exists(session, "current_bus_matrix"):
            return None
        read_schema = read_schema_name_for(
            str(session.execute(text("SELECT current_schema()")).scalar())
        )
        rows = session.execute(
            text(
                "SELECT t.table_name AS fact, b.attachment AS attachment, b.roles AS roles, "
                "b.conformed_group AS conformed_group, b.needs_confirmation AS needs_confirmation "
                f'FROM "{read_schema}".current_bus_matrix b '
                "JOIN tables t ON t.table_id = b.fact_table_id"
            )
        ).all()
    return [
        SimpleNamespace(
            fact=short(r.fact),
            attachment=r.attachment,
            roles=list(r.roles),
            conformed_group=r.conformed_group,
            needs_confirmation=r.needs_confirmation,
        )
        for r in rows
    ]


@pytest.mark.llm
def test_conform_pass_produces_verdicts(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """The conform pass produces >= 1 conformed verdict when cross-fact folds exist.

    Catches the all-abstained collapse (every folded cell needs_confirmation, no
    conformed_group) — the shape a meaning-starved post-split judge produces. Skips where
    there is nothing to conform: a Tier-B corpus, a pre-DAT-762 engine, a normalized run with
    no folds, or folds that never span >= 2 facts.
    """
    require_pipeline_run(strategy_name)
    if is_wild(metadata_truth):
        pytest.skip("Tier-B corpus declares no dimensions to conform — structural truth only")

    cells = _read_conform_cells(strategy_name)
    if cells is None:
        pytest.skip("current_bus_matrix absent — the run predates the DAT-762 engine build")

    summary = grade_bus_matrix_conform(cells)
    if not summary.folded:
        pytest.skip("no folded bus-matrix cells — a normalized corpus, nothing to conform")
    if not summary.cross_fact_keys:
        pytest.skip(
            "no fold key spans >= 2 facts — no cross-fact identity to conform on this shape"
        )

    print(
        f"\n[bus-matrix conform] {summary.conformed} conformed / {summary.needs_confirmation} "
        f"needs_confirmation across {summary.folded} folded cells "
        f"({summary.cross_fact_keys} cross-fact fold keys) on {strategy_name}"
    )
    assert not summary.collapsed, (
        f"the conform pass produced ZERO conformed verdicts across {summary.cross_fact_keys} "
        "cross-fact fold key(s) — every folded cell collapsed to needs_confirmation. This is "
        "the all-abstained collapse: the post-split dimension_hierarchies judge adjudicated no "
        "cross-fact identity (a meaning-starved conform read, not a corpus without folds)."
    )
