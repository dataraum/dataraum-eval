"""Detector recall — does each detector find its known injection?

For each injection in entropy_map.yaml, the corresponding detector must
produce a score > DETECTION_THRESHOLD for the affected target. Column-scoped
detectors are checked per-column; table/view-scoped detectors are checked
per-table or per-view.

This is the core calibration test. A failing test means a detector is broken,
not that the test needs weakening.

Two strategies cover all 15 detectors:
- detection-v1: comprehensive (no type-breaking). 13 detectors.
- detection-typing-v1: type_fidelity + temporal_entropy (breaks types,
  run separately to avoid interference with downstream detectors).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import pytest
import yaml

# Minimum score for a detector to be considered "detected the injection"
DETECTION_THRESHOLD = 0.3

# Surprise / disagreement detectors (DAT-442) emit honest, often-small scores — a
# KL surprise (benford). For these, recall is the ORDERING "injected > clean + margin"
# (the column is measurably more entropic than clean), NOT a point threshold: >0.3 is
# the Goodhart trap when the real signal is a clean separation from near-zero clean
# (see test_adjudication_recall).
#
# The DAT-442 boost-curve removals join the ordering grammar: type_fidelity (quarantine
# rate), derived_value (formula-mismatch rate) and relationship_entropy (orphan rate)
# now emit the HONEST rate — an 8% quarantine is 0.08, a 20% orphan rate 0.20 — which
# sits below the old 0.3 point threshold the boosts were tuned to clear. Severity per
# intent lives in loss.yaml; recall is the separation from clean. (relationship_entropy
# max-aggregates the orphan rate with flat cardinality/semantic priors, so its ordering
# needs the integration gate to confirm the orphan signal dominates the max — see note.)
# A true rate that clears 0.3 honestly (null_ratio at 40%) keeps the point threshold.
#
# cross_table_consistency joined the asserted slice with DAT-432/L7 (validation wired
# through operatingModelWorkflow) and is judged by ordering below — proven in batch-2.
# dimension_coverage stays unasserted: intrinsic-complexity scalar, no injection
# exercises it (honest mean NULL rate; verified scoring at table grain, B2).
ORDERING_DETECTORS = frozenset(
    {
        "benford",
        "type_fidelity",
        "derived_value",
        "relationship_entropy",
        "cross_table_consistency",
        # slice_conditional_null was here (DAT-473) but DEMOTED 2026-06-22 (DAT-540) —
        # see DEMOTED_DETECTORS below; it is no longer a recall-graded band detector.
    }
)
ORDERING_MARGIN = 0.05

EVAL_ROOT = Path(__file__).parent.parent

# Detectors that don't exist yet — always skip
NOT_IMPLEMENTED = frozenset(
    {
        "derived_value_consistency",
    }
)

# Detectors CUT in the DAT-442 reset. Their injection may remain in the strategy as
# documented test data (the 1.35× drift, the 5%@10x outlier burst), but no live
# detector asserts on it — the statistic provably can't separate the injection from
# natural financial structure. Skip with the honest reason, not the "not yet wired"
# default (which would wrongly imply the detector is coming back).
CUT_DETECTORS: dict[str, str] = {
    "temporal_drift": (
        "CUT (DAT-442): distribution drift can't separate a shift from natural "
        "volatility on additive flows; real drift → DAT-445 expected-variation model"
    ),
    "slice_variance": (
        "CUT (DAT-442): a between-slice k-sample test is blind to the slice-global "
        "injections the eval creates; see calibration/unit/test_slice_variance_recorded.py"
    ),
    "outlier_rate": (
        "CUT (DAT-442): absolute single-column IQR/z-score can't separate an injected "
        "burst from clean financial heavy tails; see calibration/unit/test_outlier_rate_recorded.py"
    ),
}

# Detectors DEMOTED off the loss path → informative DirectSignal (benford lane). The
# detector still RUNS and emits its score (so an injection may remain in the strategy as
# documented test data), but it no longer drives readiness bands and is no longer a
# recall-graded band detector — its band-impact verdict lives in the eval catalog, not a
# recall ordering assertion. Skip with the honest DEMOTE reason (NOT "not yet wired", NOT
# CUT — the statistic still computes as context).
DEMOTED_DETECTORS: dict[str, str] = {
    "dimensional_entropy": (
        "DEMOTED (2026-06-16): NMI is anti-predictive on the loss path (highest on clean "
        "intrinsic structure, blind to the dependency violation); informative DirectSignal "
        "now — recall n/a. See entropy_eval_architecture.md + detector_coverage.yaml."
    ),
    "slice_conditional_null": (
        "DEMOTED (2026-06-22, DAT-540): its only observable band move is a false positive "
        "on a benign optional FK (payment_id V=0.97→blocked), and on its injected columns "
        "the band is already set by cross_table_consistency (confounded); informative "
        "DirectSignal now — recall n/a. See entropy_eval_architecture.md + "
        "scripts/calibrate_band_impact_ablation.py."
    ),
}

# Detectors the current slice actually runs. Two workflows drive them:
#   - addSourceWorkflow → terminal `detect` (DAT-394): the table-local +
#     source-level detectors source-wide — type_fidelity, null_ratio,
#     business_meaning, unit_entropy, temporal_entropy, benford.
#   - beginSessionWorkflow → terminal `session_detect` (DAT-408/DAT-403): the
#     cross-table relationship detectors (relationship_entropy) plus the value
#     layer — dimensional_entropy, derived_value (slicing → … → correlations,
#     wired 2026-06-05; scoring verified after the DAT-405 loader head-fallback
#     fix). (slice_variance AND outlier_rate were CUT in the DAT-442 reset — both
#     hit the wall where the statistic can't separate the injection from natural
#     financial structure; see calibration/unit/test_slice_variance_recorded.py
#     and test_outlier_rate_recorded.py.)
#     join_path_determinism ALSO runs here and its precision fix is verified
#     (PR #207), but it has no recall fixture yet: add_duplicate_fk_paths tests
#     redundancy the LLM dedupes, not genuine ambiguity — that needs two
#     DISTINCT FKs to the same table (DAT-419 testdata gap), so join_path stays
#     out of the asserted slice until such a fixture exists.
# Move ids out of OUT_OF_SLICE_REASON into here as later phases (and their detect
# steps) get wired into the workflows.
CURRENT_SLICE_DETECTORS = frozenset(
    {
        "type_fidelity",
        "null_ratio",
        "slice_conditional_null",
        "business_meaning",
        "unit_entropy",
        "temporal_entropy",
        "benford",
        "relationship_entropy",
        "dimensional_entropy",
        "derived_value",
        # DAT-432/L7: the eval driver now runs operatingModelWorkflow, whose
        # terminal operating_model_detect scores the executed validations.
        "cross_table_consistency",
    }
)

# Why each out-of-slice detector produces no score yet (empty since DAT-432
# wired validation; repopulate as new phases land ahead of their detect).
# ``driver_rankings`` is not an entropy-band detector at all: the driver-discovery
# phase (DAT-546) emits a per-measure ranking, not a column entropy score, so its
# injection (inject_driver_effect, DAT-688) is graded by ORDERING in
# calibration/test_driver_recall.py — never by a band score here.
OUT_OF_SLICE_REASON: dict[str, str] = {
    "driver_rankings": (
        "driver_rankings is a driver-discovery oracle (DAT-688), not a band-scored "
        "entropy detector — recall is graded by ordering in test_driver_recall.py "
        "(cost_center significant vs clean + slice effects monotone in factor)"
    ),
}

# Detectors where the injection is known-misaligned (documents the gap)
KNOWN_MISALIGNED = frozenset(
    {
        "unit_entropy",  # Measures metadata, injection corrupts values
    }
)

# Injections where the detector can't see the specific target column.
# Key: (detector_id, table, column). Reason documented inline.
# (Empty since DAT-444 remapped the trial_balance drift_formula injection to
# cross_table_consistency — the TB↔GL identity is a cross-table aggregate.)
KNOWN_DETECTOR_GAPS: dict[tuple[str, str, str], str] = {}

# Detectors where LLM non-determinism makes the score vary across runs.
# Use @pytest.mark.xfail(strict=False) — test shows XPASS when detection works,
# XFAIL when LLM grounding reduces the score below threshold.
LLM_NONDETERMINISTIC: dict[tuple[str, str, str], str] = {
    ("business_meaning", "invoices", "rrFlp_11_zp00"): (
        "LLM sometimes identifies business_concept from data values despite garbage name. "
        "ontology_bonus then reduces score below threshold. Non-deterministic."
    ),
    ("business_meaning", "invoices", "xQ_v7kL"): (
        "LLM sometimes identifies business_concept from data values despite garbage name. "
        "ontology_bonus then reduces score below threshold. Non-deterministic."
    ),
    # Wholesale formula divergence scores through the name-hypothesis identity
    # conflict (the rows follow formula B perfectly, so the mismatch leg is 0;
    # the NAMED claim carries the entropy) — and the hypothesis is LLM-emitted
    # per run and hygiene-gated (min rows + confidence), so it may not fire on a
    # given head. XPASS when it lands (3/3 fired on the wave-2 cal run; a
    # 2026-06-11 teach re-run re-rolled advertising_avg_price to no-hypothesis).
    ("derived_value", "formula_probes", "advertising_avg_price"): (
        "wholesale recall rides the LLM name-hypothesis; may not fire on a given run"
    ),
    ("derived_value", "formula_probes", "handling_net"): (
        "wholesale recall rides the LLM name-hypothesis; may not fire on a given run"
    ),
    ("derived_value", "formula_probes", "storage_value"): (
        "undiscoverable (scaled) actual formula: the score is the graded LLM "
        "name-hypothesis mismatch; the hypothesis may not fire on a given run"
    ),
}


@functools.cache
def _expected_formula_answers() -> frozenset[tuple[str, str]]:
    """(raw table, column) pairs answered by a persisted expected_formula teach (DAT-447).

    Direct ``config_overlay`` read, the same surface ``load_declared_formula``
    consumes — ``superseded_at IS NULL`` filters undone teaches.
    """
    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from sqlalchemy import text

    from calibration import runner as runner_mod

    runner_mod.bootstrap_engine()
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT payload FROM config_overlay "
                    "WHERE type = 'validation' AND superseded_at IS NULL"
                )
            ).all()
    finally:
        mgr.close()
    answers: set[tuple[str, str]] = set()
    for r in rows:
        payload = r.payload or {}
        if payload.get("check_type") != "expected_formula":
            continue
        params = payload.get("parameters") or {}
        if params.get("table") and params.get("column"):
            answers.add((str(params["table"]).lower(), str(params["column"]).lower()))
    return frozenset(answers)


def _answered_by_teach(table: str, column: str, detector: str) -> bool:
    """Has a persisted teach already declared this injection's true answer?

    Only the derived_value expected_formula declaration exists today; the
    declared table is the source-qualified raw name, so the bare entropy_map
    table matches by substring.
    """
    if detector != "derived_value":
        return False
    column_lc = column.lower()
    return any(
        table.lower() in declared_table and declared_column == column_lc
        for declared_table, declared_column in _expected_formula_answers()
    )


def _injection_id(injection: dict[str, Any]) -> str:
    """Human-readable ID for parametrize."""
    table = injection["target_file"].replace(".csv", "")
    return f"{injection['detector_id']}:{table}.{injection['target_column']}"


def _get_injections(strategy: str) -> list[dict[str, Any]]:
    """Load injections for parametrize (runs at collection time)."""
    path = EVAL_ROOT / "data" / strategy / "entropy_map.yaml"
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    result: list[dict[str, Any]] = data.get("injections", [])
    return result


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Dynamically parametrize injection tests based on --strategy."""
    if "injection" in metafunc.fixturenames:
        strategy = metafunc.config.getoption("--strategy", default="detection-v1")
        injections = _get_injections(strategy)
        ids = [_injection_id(inj) for inj in injections]
        metafunc.parametrize("injection", injections, ids=ids)


def _find_score(
    table: str,
    column: str,
    detector: str,
    pipeline_scores: dict[tuple[str, str, str], float],
    pipeline_table_scores: dict[tuple[str, str], float],
    pipeline_view_scores: dict[tuple[str, str], float],
    pipeline_relationship_scores: dict[tuple[str, str, str], float],
) -> float | None:
    """Find a detector score across column, relationship, table, and view scopes."""
    # Column-scoped: exact (table, column, detector) match
    score = pipeline_scores.get((table, column, detector))
    if score is not None:
        return score

    # Relationship-scoped (DAT-408): the score is indexed under BOTH endpoint
    # columns, so the injected FK column (e.g. payments.invoice_id) matches exactly;
    # the (table, detector) fallback covers a typed-name mismatch on this endpoint.
    score = pipeline_relationship_scores.get((table, column, detector))
    if score is not None:
        return score
    rel_best = None
    for (t, _, d), s in pipeline_relationship_scores.items():
        if t == table and d == detector and (rel_best is None or s > rel_best):
            rel_best = s
    if rel_best is not None:
        return rel_best

    # Table-scoped: (table, detector) match
    score = pipeline_table_scores.get((table, detector))
    if score is not None:
        return score

    # View-scoped: any view matching this detector
    for (_, d), s in pipeline_view_scores.items():
        if d == detector:
            return s

    # Column-scoped fallback: best score for this (table, detector) across all columns.
    # Handles derived_value where injection on column A breaks a formula attributed
    # to column B (correlations dedup picks sum over difference).
    best = None
    for (t, _, d), s in pipeline_scores.items():
        if t == table and d == detector:
            if best is None or s > best:
                best = s
    return best


def test_injection_detected(
    injection: dict[str, Any],
    pipeline_scores: dict[tuple[str, str, str], float],
    pipeline_table_scores: dict[tuple[str, str], float],
    pipeline_view_scores: dict[tuple[str, str], float],
    pipeline_relationship_scores: dict[tuple[str, str, str], float],
    clean_pipeline_scores: dict[tuple[str, str, str], float],
    request: pytest.FixtureRequest,
) -> None:
    """Each known injection must produce an elevated score for the affected column."""
    table = injection["target_file"].replace(".csv", "")
    column = injection["target_column"]
    detector = injection["detector_id"]

    # Calibration NEGATIVES: generative families record their labelled-clean
    # legs in the entropy_map too (the rig's true-negative class — agree-stratum
    # formulas, clean genuine FKs). They are precision material by construction,
    # never recall targets; asserting detection on them inverts their meaning.
    params = injection.get("parameters", {})
    if params.get("divergence_mode") == "agree" or params.get("stratum") == "genuine_clean":
        pytest.skip(
            "calibration negative — the labelled-CLEAN leg of a generative family "
            "(precision material, not a recall target)"
        )

    # Teach-ANSWERED injection (DAT-447): a persisted expected_formula teach
    # declares this column's true formula, so every subsequent head legitimately
    # scores it CLOSED — the closure contract working (test_teach_cycle proves
    # the drop; recall was proven banded on the pre-teach head), not a recall
    # miss. Asserting recall forever would forbid teach-closure on any
    # calibration session.
    if _answered_by_teach(table, column, detector):
        pytest.skip(
            "injection answered by a persisted expected_formula teach — closed by design "
            "(DAT-447; see test_teach_cycle.py::test_teach_closure[validation])"
        )

    # Always skip unimplemented detectors
    if detector in NOT_IMPLEMENTED:
        pytest.skip(f"{detector} not implemented yet")

    # Skip detectors cut in the DAT-442 reset (honest reason, not "not yet wired").
    if detector in CUT_DETECTORS:
        pytest.skip(CUT_DETECTORS[detector])

    # Skip detectors DEMOTED off the loss path → informative DirectSignal. The detector
    # still runs, but it is no longer a recall-graded band detector (verdict in the catalog).
    if detector in DEMOTED_DETECTORS:
        pytest.skip(DEMOTED_DETECTORS[detector])

    # Skip detectors whose phase/detect-step the current workflow slice doesn't
    # run yet (DAT-370 add_source slice). Not a regression — the detector simply
    # never executes. These light up as later phases get wired; the assertions
    # below (and the xfail markers) re-apply once a detector is back in scope.
    if detector not in CURRENT_SLICE_DETECTORS:
        pytest.skip(
            OUT_OF_SLICE_REASON.get(
                detector, f"{detector}: phase not yet wired into the addSourceWorkflow slice"
            )
        )

    # Mark known-misaligned injections as expected failures
    if detector in KNOWN_MISALIGNED:
        pytest.xfail(f"{detector} injection is known-misaligned (see CLAUDE.md)")

    # Mark specific detector+target gaps as expected failures
    gap_key = (detector, table, column)
    if gap_key in KNOWN_DETECTOR_GAPS:
        pytest.xfail(KNOWN_DETECTOR_GAPS[gap_key])

    # LLM non-determinism: score varies between runs. strict=False lets us
    # see XPASS when detection works and XFAIL when ontology_bonus hides it.
    if gap_key in LLM_NONDETERMINISTIC:
        request.node.add_marker(
            pytest.mark.xfail(reason=LLM_NONDETERMINISTIC[gap_key], strict=False)
        )

    # Pipeline lowercases column names during import
    column_lc = column.lower()

    # Some injections affect multiple columns (e.g., debit/credit mutex)
    if "/" in column:
        cols = column_lc.split("/")
        scores = [
            _find_score(
                table,
                c,
                detector,
                pipeline_scores,
                pipeline_table_scores,
                pipeline_view_scores,
                pipeline_relationship_scores,
            )
            for c in cols
        ]
        best = max((s for s in scores if s is not None), default=None)
        assert best is not None, (
            f"{detector} produced no score for {table}.{{{column}}} — "
            f"detector didn't run or doesn't cover this injection type"
        )
        assert best > DETECTION_THRESHOLD, (
            f"{detector} scored {best:.3f} for {table}.{{{column}}} — "
            f"injection missed (threshold={DETECTION_THRESHOLD})"
        )
        return

    score = _find_score(
        table,
        column_lc,
        detector,
        pipeline_scores,
        pipeline_table_scores,
        pipeline_view_scores,
        pipeline_relationship_scores,
    )
    assert score is not None, (
        f"{detector} produced no score for {table}.{column} — "
        f"detector didn't run or doesn't cover this injection type"
    )

    clean = clean_pipeline_scores.get((table, column_lc, detector), 0.0)
    delta = score - clean

    if detector in ORDERING_DETECTORS:
        # Ordering grammar: injected must sit a clear margin above clean. The
        # absolute score is honestly modest (a divergence), so a point threshold
        # would wrongly read "missed" while the detector cleanly separates.
        assert delta > ORDERING_MARGIN, (
            f"{detector} scored {score:.3f} for {table}.{column} "
            f"(clean={clean:.3f}, delta={delta:+.3f}) — not measurably above clean "
            f"(margin={ORDERING_MARGIN})"
        )
        return

    assert score > DETECTION_THRESHOLD, (
        f"{detector} scored {score:.3f} for {table}.{column} "
        f"(clean={clean:.3f}, delta={delta:+.3f}) — "
        f"injection missed (threshold={DETECTION_THRESHOLD})"
    )
