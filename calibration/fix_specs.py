"""Fix specifications for calibration testing.

Each FixSpec maps an injection to the fix that resolves it: detector fires,
fix is applied, score drops. Specs are used by test_fix_calibration.py to
parametrize end-to-end fix tests.

Phase 1: accept_finding fixes (config-only, quality_review re-run)
Phase 2: metadata fixes (direct DB update, no phase re-run needed)
Phase 3: config fixes requiring earlier phase re-runs (typing, relationships)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dataraum.pipeline.fixes.models import FixDocument


@dataclass
class FixSpec:
    """Specification for a single fix calibration test."""

    detector_id: str
    table: str
    column: str
    action: str
    fix_documents: list[FixDocument]
    expected_max_score: float
    requires_rerun: str = "quality_review"
    phase: int = 1  # Phase 1 = accept_finding, Phase 2 = semantic/typing
    xfail_reason: str | None = None

    @property
    def test_id(self) -> str:
        return f"{self.detector_id}:{self.table}.{self.column}:{self.action}"


def _accept_finding_doc(
    detector_id: str,
    table: str,
    column: str,
    dimension: str,
) -> FixDocument:
    """Build a FixDocument for accept_finding action (config target)."""
    return FixDocument(
        target="config",
        action="accept_finding",
        table_name=table,
        column_name=column,
        dimension=dimension,
        payload={
            "config_path": "entropy/thresholds.yaml",
            "key_path": ["detectors", detector_id, "accepted_columns"],
            "operation": "append",
            "value": f"{table}.{column}",
        },
        description=f"accept_finding: {table}.{column} for {detector_id}",
    )


def _set_column_type_doc(
    table: str,
    column: str,
    target_type: str,
) -> FixDocument:
    """Build a FixDocument for set_column_type action (config target)."""
    return FixDocument(
        target="config",
        action="set_column_type",
        table_name=table,
        column_name=column,
        dimension="structural.types.type_fidelity",
        payload={
            "config_path": "phases/typing.yaml",
            "key_path": ["overrides", "forced_types"],
            "operation": "merge",
            "value": {f"{table}.{column}": {"target_type": target_type}},
        },
        description=f"set_column_type: {table}.{column} → {target_type}",
    )


def _add_type_pattern_doc(
    table: str,
    column: str,
    pattern_name: str,
    pattern: str,
    standardization_expr: str,
    inferred_type: str = "DATE",
) -> FixDocument:
    """Build a FixDocument for add_type_pattern action (config target)."""
    return FixDocument(
        target="config",
        action="add_type_pattern",
        table_name=table,
        column_name=column,
        dimension="semantic.temporal",
        payload={
            "config_path": "phases/typing.yaml",
            "key_path": ["overrides", "patterns"],
            "operation": "merge",
            "value": {
                pattern_name: {
                    "pattern": pattern,
                    "standardization_expr": standardization_expr,
                    "inferred_type": inferred_type,
                },
            },
        },
        description=f"add_type_pattern: {pattern_name} for {table}.{column}",
    )


def _metadata_fix_doc(
    model: str,
    table: str,
    column: str,
    dimension: str,
    action: str,
    field_updates: dict[str, Any],
    description: str,
) -> FixDocument:
    """Build a FixDocument for a metadata fix (direct DB update)."""
    return FixDocument(
        target="metadata",
        action=action,
        table_name=table,
        column_name=column,
        dimension=dimension,
        payload={
            "model": model,
            "field_updates": field_updates,
        },
        description=description,
    )


# ---------------------------------------------------------------------------
# Phase 1: accept_finding fixes (config-only, quality_review re-run)
# ---------------------------------------------------------------------------

PHASE1_FIX_SPECS: list[FixSpec] = [
    FixSpec(
        detector_id="outlier_rate",
        table="journal_lines",
        column="credit",
        action="accept_finding",
        fix_documents=[
            _accept_finding_doc(
                "outlier_rate", "journal_lines", "credit", "value.outliers",
            ),
        ],
        expected_max_score=0.2,
    ),
    FixSpec(
        detector_id="benford",
        table="bank_transactions",
        column="amount",
        action="accept_finding",
        fix_documents=[
            _accept_finding_doc(
                "benford", "bank_transactions", "amount", "value.distribution",
            ),
        ],
        expected_max_score=0.2,
    ),
    FixSpec(
        detector_id="null_ratio",
        table="journal_lines",
        column="cost_center",
        action="accept_finding",
        fix_documents=[
            _accept_finding_doc(
                "null_ratio", "journal_lines", "cost_center", "value.nulls",
            ),
        ],
        expected_max_score=0.1,
    ),
    FixSpec(
        detector_id="relationship_entropy",
        table="payments",
        column="invoice_id",
        action="accept_finding",
        fix_documents=[
            _accept_finding_doc(
                "relationship_entropy", "payments", "invoice_id",
                "structural.relations.relationship_quality",
            ),
        ],
        expected_max_score=0.2,
    ),
]

# ---------------------------------------------------------------------------
# Phase 2: metadata fixes (direct DB update, no phase re-run needed)
# Uses MetadataInterpreter to update SemanticAnnotation/Relationship rows
# directly, then measure_at_gate re-reads the updated metadata.
# ---------------------------------------------------------------------------

PHASE2_FIX_SPECS: list[FixSpec] = [
    FixSpec(
        detector_id="business_meaning",
        table="invoices",
        column="rrflp_11_zp00",
        action="document_business_meaning",
        fix_documents=[
            _metadata_fix_doc(
                model="SemanticAnnotation",
                table="invoices",
                column="rrflp_11_zp00",
                dimension="semantic.business_meaning",
                action="document_business_meaning",
                field_updates={
                    "business_name": "Revenue Flag Period 11",
                    "entity_type": "financial_flag",
                    "business_description": "Revenue recognition indicator for period 11",
                    "confidence": 1.0,
                },
                description="Document business meaning for invoices.rrflp_11_zp00",
            ),
        ],
        expected_max_score=0.1,
        requires_rerun="semantic",
        phase=2,
    ),
    FixSpec(
        detector_id="business_meaning",
        table="invoices",
        column="xq_v7kl",
        action="document_business_meaning",
        fix_documents=[
            _metadata_fix_doc(
                model="SemanticAnnotation",
                table="invoices",
                column="xq_v7kl",
                dimension="semantic.business_meaning",
                action="document_business_meaning",
                field_updates={
                    "business_name": "Quality Control Code",
                    "entity_type": "classification",
                    "business_description": "Quality control classification code",
                    "confidence": 1.0,
                },
                description="Document business meaning for invoices.xq_v7kl",
            ),
        ],
        expected_max_score=0.1,
        requires_rerun="semantic",
        phase=2,
    ),
    FixSpec(
        detector_id="temporal_entropy",
        table="payments",
        column="date",
        action="set_timestamp_role",
        fix_documents=[
            _metadata_fix_doc(
                model="SemanticAnnotation",
                table="payments",
                column="date",
                dimension="semantic.temporal",
                action="set_timestamp_role",
                field_updates={"semantic_role": "timestamp"},
                description="Set timestamp role for payments.date",
            ),
        ],
        expected_max_score=0.3,
        requires_rerun="semantic",
        phase=2,
        xfail_reason=(
            "Column already marked as timestamp; the issue is type mismatch "
            "(VARCHAR from corrupt dates) — set_timestamp_role is a no-op. "
            "See add_type_pattern spec in Phase 3 for the real fix."
        ),
    ),
]

# ---------------------------------------------------------------------------
# Phase 3: config fixes requiring earlier phase re-runs
# These write to phase config (e.g. typing.yaml) and need the pipeline to
# re-run from that phase. The runner cleans the affected phase, then runs
# the pipeline through quality_review.
# ---------------------------------------------------------------------------

PHASE3_FIX_SPECS: list[FixSpec] = [
    FixSpec(
        detector_id="temporal_entropy",
        table="payments",
        column="date",
        action="add_type_pattern",
        fix_documents=[
            _add_type_pattern_doc(
                table="payments",
                column="date",
                pattern_name="mon_dd_yyyy",
                pattern=r"^[A-Za-z]{3}\s\d{1,2},\s\d{4}$",
                standardization_expr='STRPTIME("{col}", \'%b %d, %Y\')',
                inferred_type="DATE",
            ),
            _add_type_pattern_doc(
                table="payments",
                column="date",
                pattern_name="epoch_seconds",
                pattern=r"^\d{10,11}$",
                standardization_expr='CAST(to_timestamp(TRY_CAST("{col}" AS BIGINT)) AS DATE)',
                inferred_type="DATE",
            ),
        ],
        expected_max_score=0.2,
        requires_rerun="typing",
        phase=3,
    ),
    FixSpec(
        detector_id="type_fidelity",
        table="journal_lines",
        column="debit",
        action="set_column_type",
        fix_documents=[
            _set_column_type_doc("journal_lines", "debit", "VARCHAR"),
        ],
        expected_max_score=0.1,
        requires_rerun="typing",
        phase=3,
    ),
    FixSpec(
        detector_id="relationship_entropy",
        table="payments",
        column="invoice_id",
        action="confirm_relationship",
        fix_documents=[],
        expected_max_score=0.3,
        requires_rerun="relationships",
        phase=3,
        xfail_reason=(
            "Orphan rate (ri_entropy=0.447 from sqrt-boosted 20%) dominates "
            "via max aggregation; confirm_relationship only reduces semantic "
            "component — accept_finding is the working fix path (Phase 1)"
        ),
    ),
]

ZONE1_FIX_SPECS: list[FixSpec] = PHASE1_FIX_SPECS + PHASE2_FIX_SPECS + PHASE3_FIX_SPECS
