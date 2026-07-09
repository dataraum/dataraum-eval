"""Agent-metadata ground-truth oracle — the DAT-680 P1 assertion-layer seed.

Loads ``calibration/fixtures/metadata_truth.yaml`` (the hand-authored ground
truth for the finance corpus) and reads the engine's persisted agent/derived
metadata from the ``current_*`` read views, so a calibration test can grade the
AGENT layer the way detectors are already graded against ``entropy_map.yaml``.

First surface (DAT-718): ``metric_additivity``. Sibling readers (relationships,
roles, cycles) land with DAT-684/685/686 — each is one ``current_*`` view read
plus a named set-statistic vs this file, following the shape below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FIXTURE = Path(__file__).parent / "fixtures" / "metadata_truth.yaml"


def load_truth() -> dict[str, Any]:
    """The parsed ``metadata_truth.yaml`` ground truth."""
    truth: dict[str, Any] = yaml.safe_load(FIXTURE.read_text())
    return truth


@dataclass(frozen=True)
class AdditivityVerdict:
    """One drill target's additivity verdict — the four graded fields."""

    categorical_additive: bool
    time_additive: bool
    categorical_reason: str | None
    time_reason: str | None


def read_metric_additivity(session: Any) -> dict[tuple[str, str], AdditivityVerdict]:
    """Every ``current_metric_additivity`` row, keyed ``(target_kind, target_key)``.

    Reads the promoted operating_model head via the ``<ws>_read`` schema — the
    same ``current_*`` surface the drill (cockpit) reads, not the raw versioned
    table — so the oracle grades exactly what the product would consume.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT target_kind, target_key, categorical_additive, time_additive, "
            "categorical_reason, time_reason "
            f'FROM "{read_schema}".current_metric_additivity'
        )
    ).all()
    return {
        (r.target_kind, r.target_key): AdditivityVerdict(
            categorical_additive=bool(r.categorical_additive),
            time_additive=bool(r.time_additive),
            categorical_reason=r.categorical_reason,
            time_reason=r.time_reason,
        )
        for r in rows
    }


def expected_additivity(truth: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Flatten ``metric_additivity`` to ``(target_kind, target_key) -> spec``."""
    block = truth.get("metric_additivity") or {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for kind in ("metric", "measure"):
        for key, spec in (block.get(f"{kind}s") or {}).items():
            out[(kind, key)] = spec
    return out


def read_temporal_behavior(session: Any) -> dict[str, str]:
    """``current_column_concepts.temporal_behavior`` keyed ``"table.column"`` (narrow names).

    The catalogue-grain stock/flow verdict (DAT-637 re-homed it to ``ColumnConcept``)
    — the surface DAT-685 grades against ``metadata_truth.stock_flow``. Only columns
    the detector resolved (``temporal_behavior IS NOT NULL``) are returned.
    """
    from dataraum.storage.read_views import read_schema_name_for
    from sqlalchemy import text

    from calibration.tools._runs import short

    read_schema = read_schema_name_for(
        str(session.execute(text("SELECT current_schema()")).scalar())
    )
    rows = session.execute(
        text(
            "SELECT t.table_name AS table_name, c.column_name AS column_name, "
            "cc.temporal_behavior AS temporal_behavior "
            f'FROM "{read_schema}".current_column_concepts cc '
            f'JOIN "{read_schema}".current_columns c ON c.column_id = cc.column_id '
            f'JOIN "{read_schema}".current_tables t ON t.table_id = c.table_id '
            "WHERE cc.temporal_behavior IS NOT NULL"
        )
    ).all()
    return {f"{short(r.table_name)}.{r.column_name}": r.temporal_behavior for r in rows}
