"""Fix specifications for calibration testing.

Each FixSpec declares the intent: detector fires -> action applied -> score drops.
The bridge layer in dataraum-context resolves fix routing from the action name
alone via fixes.yaml schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FixSpec:
    """Specification for a single fix calibration test."""

    detector_id: str
    table: str
    column: str
    action: str                           # e.g. "document_accepted_outlier_rate"
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_max_score: float = 0.2
    xfail_reason: str | None = None

    @property
    def test_id(self) -> str:
        base = f"{self.detector_id}:{self.table}.{self.column}:{self.action}"
        # Disambiguate multi-pattern specs (e.g. two document_type_pattern entries)
        if "pattern_name" in self.parameters:
            base += f"[{self.parameters['pattern_name']}]"
        return base

    @property
    def is_acceptance(self) -> bool:
        return self.action.startswith("document_accepted_")


# ---------------------------------------------------------------------------
# Zone 1 Fix Specs
# ---------------------------------------------------------------------------

ZONE1_FIX_SPECS: list[FixSpec] = [
    # Acceptance fixes
    FixSpec(
        detector_id="outlier_rate",
        table="journal_lines",
        column="credit",
        action="document_accepted_outlier_rate",
        expected_max_score=0.2,
    ),
    FixSpec(
        detector_id="benford",
        table="bank_transactions",
        column="amount",
        action="document_accepted_benford",
        expected_max_score=0.2,
    ),
    FixSpec(
        detector_id="null_ratio",
        table="journal_lines",
        column="cost_center",
        action="document_accepted_null_ratio",
        expected_max_score=0.1,
    ),
    FixSpec(
        detector_id="relationship_entropy",
        table="payments",
        column="invoice_id",
        action="document_accepted_relationship_quality",
        expected_max_score=0.2,
    ),
    # Metadata fixes
    FixSpec(
        detector_id="business_meaning",
        table="invoices",
        column="rrflp_11_zp00",
        action="document_business_name",
        parameters={
            "business_name": "Revenue Flag Period 11",
            "entity_type": "financial_flag",
            "business_description": "Revenue recognition indicator for period 11",
            "confidence": 1.0,
        },
        expected_max_score=0.1,
    ),
    FixSpec(
        detector_id="business_meaning",
        table="invoices",
        column="xq_v7kl",
        action="document_business_name",
        parameters={
            "business_name": "Quality Control Code",
            "entity_type": "classification",
            "business_description": "Quality control classification code",
            "confidence": 1.0,
        },
        expected_max_score=0.1,
    ),
    FixSpec(
        detector_id="temporal_entropy",
        table="payments",
        column="date",
        action="document_timestamp_role",
        parameters={"semantic_role": "timestamp"},
        expected_max_score=0.3,
        xfail_reason=(
            "Column already marked as timestamp; the issue is type mismatch "
            "(VARCHAR from corrupt dates) — document_timestamp_role is a no-op. "
            "See document_type_pattern specs for the real fix."
        ),
    ),
    # Config fixes (preprocess — require phase re-run)
    FixSpec(
        detector_id="temporal_entropy",
        table="payments",
        column="date",
        action="document_type_pattern",
        parameters={
            "pattern_name": "mon_dd_yyyy",
            "pattern": r"^[A-Za-z]{3}\s\d{1,2},\s\d{4}$",
            "standardization_expr": 'STRPTIME("{col}", \'%b %d, %Y\')',
        },
        expected_max_score=0.2,
    ),
    FixSpec(
        detector_id="temporal_entropy",
        table="payments",
        column="date",
        action="document_type_pattern",
        parameters={
            "pattern_name": "epoch_seconds",
            "pattern": r"^\d{10,11}$",
            "standardization_expr": 'CAST(to_timestamp(TRY_CAST("{col}" AS BIGINT)) AS DATE)',
        },
        expected_max_score=0.2,
    ),
    FixSpec(
        detector_id="type_fidelity",
        table="journal_lines",
        column="debit",
        action="document_type_override",
        parameters={"target_type": "VARCHAR"},
        expected_max_score=0.1,
    ),
    FixSpec(
        detector_id="relationship_entropy",
        table="payments",
        column="invoice_id",
        action="document_relationship",
        parameters={
            "from_table": "payments",
            "to_table": "invoices",
            "relationship_type": "foreign_key",
        },
        expected_max_score=0.3,
        xfail_reason=(
            "Orphan rate (ri_entropy=0.447 from sqrt-boosted 20%) dominates "
            "via max aggregation; document_relationship only reduces semantic "
            "component — document_accepted_relationship_quality is the working fix path"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Zone 2 Fix Specs
# ---------------------------------------------------------------------------

ZONE2_FIX_SPECS: list[FixSpec] = [
    FixSpec(
        detector_id="temporal_drift",
        table="bank_transactions",
        column="amount",
        action="document_accepted_temporal_drift",
        parameters={"reason": "Expected seasonal pattern in bank transactions"},
        expected_max_score=0.2,
    ),
    FixSpec(
        detector_id="dimensional_entropy",
        table="journal_lines",
        column="debit/credit",
        action="confirm_expected_pattern",
        parameters={
            "table": "journal_lines",
            "columns": "debit,credit",
            "pattern_type": "mutual_exclusivity",
            "description": (
                "Double-entry bookkeeping: each journal line has either "
                "a debit or a credit, never both."
            ),
        },
        expected_max_score=0.5,
    ),
    FixSpec(
        detector_id="derived_value",
        table="journal_lines",
        column="debit",
        action="document_accepted_formula_match",
        parameters={"reason": "Formula drift accepted — manual adjustments expected"},
        expected_max_score=0.2,
    ),
]
