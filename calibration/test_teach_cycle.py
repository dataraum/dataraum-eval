"""Unified teach-closure harness (DAT-447) — one row per teach type.

ADR-0009's whole thesis is that a *taught answer drops the disagreement*. This
module is the executable closure map of the teach vocabulary: the 9
applier-backed overlay types (engine ``core/overlay.py::appliable_teach_types``)
plus the relationship overlay family (direct ``config_overlay`` reads), one
parametrized row each, with the standard closure assertions — post-teach C-drop
and/or score-drop at the HEAD-RESOLVED read surface, and the taught object's
suggestion-consistency where applicable.

Rows come in three honesty classes:

1. **Proven from persisted runs (no LLM cost)** — ``relationship``: both the
   pre-teach and post-teach runs of detection-relationship-cal-v1's session are
   persisted; the row re-pools the claim rows per run.
2. **Proven with one pipeline re-run (real LLM, Tier 3)** — ``null_value``,
   ``concept_property``, ``unit``, ``validation``: marked ``llm``; each drives a
   teach + same-session re-run when the pre-teach state is live, and asserts the
   persisted post-teach state on re-execution.
3. **No honest scenario yet** — ``rebind``, ``concept``, ``type_pattern``,
   ``cycle``, ``metric``: parametrized SKIPs whose reasons state exactly what
   corpus member / assertion surface is missing. These skips ARE the harness's
   honest coverage map — never fake a closure.

The drop is only OBSERVABLE because scores are read head-resolved (conftest
Step-0, ``_head_resolved_entropy_rows``): a raw ``max()`` over the pre- and
post-teach runs' coexisting rows would surface the stale high C and hide the
closure.
"""

from __future__ import annotations

from collections.abc import Callable
from statistics import fmean
from typing import Any

import pytest
import yaml
from dataraum.core.connections import ConnectionConfig, ConnectionManager
from dataraum.storage.read_views import read_schema_name_for
from sqlalchemy import text

from calibration import runner as runner_mod
from calibration.conftest import DATA_DIR
from calibration.test_detector_recall import DETECTION_THRESHOLD

_DROP_MARGIN = 0.02  # anti-noise floor on signed deltas, NOT a point threshold

_NULL_STRATEGY = "detection-null-v1"
_NULL_TABLE, _NULL_COLUMN = "bank_transactions", "amount"

_UNIT_STRATEGY = "detection-unit-v1"
_UNIT_TABLE, _UNIT_COLUMN, _TAUGHT_UNIT = "bank_transactions", "amount", "EUR"

_TB_STRATEGY = "detection-v1"
_TB_TABLE, _TB_COLUMN = "trial_balance", "debit_balance"
_TB_CONCEPT = "account_balance"  # the concept debit_balance binds to (point_in_time prior)

_REL_STRATEGY = "detection-relationship-cal-v1"

_DERIVED_STRATEGY = "detection-derived-cal-v1"
_DERIVED_TABLE, _DERIVED_COLUMN = "formula_probes", "inspection_total"

_SLICE_STRATEGY = "detection-slice-null-v1"
_SLICE_TABLE, _SLICE_COLUMN, _SLICE_DIM = "journal_lines", "debit", "cost_center"


# ---------------------------------------------------------------------------
# Head-resolved read helpers (the conftest Step-0 surface)
# ---------------------------------------------------------------------------


def _head_resolved_rows(detector_id: str) -> list[Any]:
    """The workspace's current (target, score, evidence) rows for one detector.

    Head-resolved via the ``current_entropy_objects`` view (no session axis post
    DAT-506): the view returns only rows under a currently-promoted head, so a
    teach re-run's drop is visible and stale pre-teach rows are excluded.
    """
    runner_mod.bootstrap_engine()  # PG/Temporal env + workspace schema (idempotent)
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            read_schema = read_schema_name_for(
                str(s.execute(text("SELECT current_schema()")).scalar())
            )
            rows = s.execute(
                text(
                    f'SELECT target, score, evidence FROM "{read_schema}".current_entropy_objects '
                    "WHERE detector_id = :det"
                ),
                {"det": detector_id},
            ).all()
    finally:
        mgr.close()
    return list(rows)


def _column_rows(rows: list[Any], table_substr: str, column: str) -> list[Any]:
    return [r for r in rows if table_substr in r.target and r.target.endswith("." + column)]


def _load_run(strategy: str) -> runner_mod.CalibrationRun:
    """The strategy's completed run — sidecar REQUIRED; an assert pass never
    drives a pipeline.

    Activates the strategy's OWN workspace (DAT-508) so the head-resolved reads
    that follow resolve the right ``ws_<id>`` schema. The teach helpers re-activate
    the same workspace on each rerun, so the whole test stays in one workspace.

    A missing sidecar means the runner (``calibration.run``) has not driven this
    strategy since the last ``--reset`` → SKIP; the runner will drive it on its own
    pass. The old fallback ran a FULL pipeline (real LLM) from inside the test:
    run #2's assert pass silently spent ~4 min of unbudgeted LLM on a foreign
    strategy and left a two-pass workspace state that masked a recall gap.
    """
    sidecar = runner_mod.sidecar_path(strategy)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {strategy!r}; run "
            f"`python -m calibration.run -s {strategy}` first — tests never drive pipelines"
        )
    runner_mod.activate_workspace(strategy)
    return runner_mod.CalibrationRun.from_json(sidecar.read_text())


# ---------------------------------------------------------------------------
# Row: null_value (class 2 — proven e2e; the original DAT-447 scenario 6)
# ---------------------------------------------------------------------------


def _null_semantics_conflict(table_substr: str, column: str) -> float | None:
    """Head-resolved pooled conflict C for a column's null_semantics object."""
    rows = _column_rows(_head_resolved_rows("null_semantics"), table_substr, column)
    return float(rows[0].score) if rows else None


def _prove_null_value_closure() -> None:
    """A null_value teach on the injected sentinels collapses the column's conflict C.

    Runs detection-null-v1, teaches the injected sentinels as null markers, RE-RUNS
    the same session, and asserts the pooled conflict ``C`` on the taught column
    collapses. Uses ``bank_transactions.amount`` — the dense column that types
    robustly — to isolate teach-closure from the borderline-typing flake on
    journal_lines.debit (project_typing_nondeterminism).
    """
    if not (DATA_DIR / _NULL_STRATEGY).exists():
        pytest.skip(
            f"no data for {_NULL_STRATEGY}; run `python -m calibration.runner "
            f"{_NULL_STRATEGY}` first"
        )

    run = _load_run(_NULL_STRATEGY)

    before = _null_semantics_conflict(_NULL_TABLE, _NULL_COLUMN)
    if before is None:
        pytest.skip(
            f"null_semantics did not fire on {_NULL_TABLE}.{_NULL_COLUMN} in the baseline run"
        )

    emap = yaml.safe_load((DATA_DIR / _NULL_STRATEGY / "entropy_map.yaml").read_text())
    markers = next(
        inj["parameters"]["markers"]
        for inj in emap["injections"]
        if inj["target_column"] == _NULL_COLUMN and _NULL_TABLE in inj["target_file"]
    )

    runner_mod.teach_null_value_and_rerun(run, values=markers)

    after = _null_semantics_conflict(_NULL_TABLE, _NULL_COLUMN)
    assert after is not None, "null_semantics object vanished after the teach re-run"
    # Teach-closure: the taught vocabulary makes the vocabulary witness agree, so the
    # pooled conflict drops. Signed-delta grammar (ADR-0009), never a point threshold.
    assert after < before - _DROP_MARGIN, (
        f"teach did not close the conflict: C {before:.3f} -> {after:.3f} "
        f"(delta {after - before:+.3f}, expected drop > {_DROP_MARGIN})"
    )


# ---------------------------------------------------------------------------
# Row: concept_property (class 2 — mechanism wired; corpus-blocked)
# ---------------------------------------------------------------------------


def _temporal_behavior_conflict(table_substr: str, column: str) -> float | None:
    """Head-resolved pooled conflict C for a column's temporal_behavior object.

    Max over the dual-grain rows — any remaining high-C row counts against closure.
    """
    rows = _column_rows(_head_resolved_rows("temporal_behavior"), table_substr, column)
    return max((float(r.score) for r in rows), default=None)


# The LLM claim vocabulary → the ontology temporal_behavior vocabulary: the
# correction a teacher applies when the concept's declared behaviour disagrees
# with the LLM's independent reading of the column.
_ONTOLOGY_VALUE_OF_CLAIM = {"stock": "point_in_time", "flow": "additive"}


def _temporal_behavior_mislabel(
    table_substr: str, column: str
) -> tuple[float, str, str] | None:
    """The column's prior≠claim mislabel state: (conflict C, concept, correcting value).

    Selects ONLY the conflict shape concept_property can close: the ontology prior
    and the LLM claim both opine and DISAGREE — teaching the concept the value
    matching the claim makes the witnesses agree. A structural-witness dissent
    (DAT-491: data says flow while prior AND claim name-anchor to stock) is never
    selected: flipping the prior onto the structural side flips the majority
    instead of closing the disagreement (measured 2026-06-11 on detection-v1:
    teaching account_balance→additive against an 0.363 structural conflict moved
    debit_balance to an INDUCED prior≠claim C=0.771). The concept comes from the
    object's own ``teach_suggestion`` (suggestion-consistency).
    """
    rows = _column_rows(_head_resolved_rows("temporal_behavior"), table_substr, column)
    best: tuple[float, str, str] | None = None
    for r in rows:
        ev = r.evidence[0] if isinstance(r.evidence, list) and r.evidence else {}
        ont = ev.get("ontology_behavior")
        correcting = _ONTOLOGY_VALUE_OF_CLAIM.get(str(ev.get("llm_claim")))
        if not ont or correcting is None or correcting == ont:
            continue
        suggestion = ev.get("teach_suggestion") or {}
        concept = suggestion.get("concept") or _TB_CONCEPT
        score = float(r.score)
        if best is None or score > best[0]:
            best = (score, str(concept), correcting)
    return best


def _prove_concept_property_closure() -> None:
    """concept_property teach-closure for temporal_behavior — closes a prior≠claim mislabel.

    The teach (``teach_concept_property_and_rerun``: a workspace-scoped
    ``concept_property`` overlay sets a concept's ``temporal_behavior``; the re-run's
    ontology_prior leans the taught way) closes EXACTLY the prior≠claim mislabel: the
    LLM reads the column correctly while its concept's declared behaviour disagrees;
    teaching the concept the value matching the claim makes the witnesses agree and
    the pooled C collapses. The row self-selects a mislabel from the head-resolved
    evidence (``_temporal_behavior_mislabel``) and teaches the correction the object's
    own suggestion routes to.

    It SKIPS when the corpus presents no mislabel — curated finance data names columns
    the way their concepts behave (e2e 2026-06-09: on ``trial_balance.debit_balance``
    BOTH witnesses name-anchor to stock → C≈0, nothing to close); a real standing
    mislabel corpus is deferred to DAT-450. A structural-witness dissent (DAT-491) is
    out of this teach's reach by design — see ``_temporal_behavior_mislabel``. (The
    full mislabel→closure arc is ALSO proven on the generative corpus by
    ``test_stockflow_recall_teach_e2e`` when its strategy data exists.)
    """
    if not (DATA_DIR / _TB_STRATEGY).exists():
        pytest.skip(
            f"no data for {_TB_STRATEGY}; run `python -m calibration.runner {_TB_STRATEGY}` first"
        )

    run = _load_run(_TB_STRATEGY)

    mislabel = _temporal_behavior_mislabel(_TB_TABLE, _TB_COLUMN)
    if mislabel is None or mislabel[0] <= _DROP_MARGIN:
        pytest.skip(
            f"no prior≠claim mislabel conflict on {_TB_TABLE}.{_TB_COLUMN} (both witnesses "
            "name-anchor to stock — the DAT-491 boundary) → nothing concept_property can "
            "close; needs a mislabel corpus"
        )
    before, concept, value = mislabel

    runner_mod.teach_concept_property_and_rerun(run, concept=concept, value=value)

    after = _temporal_behavior_conflict(_TB_TABLE, _TB_COLUMN)
    assert after is not None, "temporal_behavior object vanished after the teach re-run"
    # Teach-closure: the taught concept behaviour makes the ontology_prior agree with the
    # LLM claim, so the pooled conflict drops. Signed-delta grammar, never a point threshold.
    assert after < before - _DROP_MARGIN, (
        f"teach did not close the conflict: C {before:.3f} -> {after:.3f} "
        f"(delta {after - before:+.3f}, expected drop > {_DROP_MARGIN})"
    )


# ---------------------------------------------------------------------------
# Row: unit (class 2 — proven e2e, DAT-428)
# ---------------------------------------------------------------------------


def _unit_entropy_detected_unit(
    table_substr: str, column: str
) -> tuple[float, str | None] | None:
    """Head-resolved (score, evidence.detected_unit) for a column's unit_entropy object."""
    rows = _column_rows(_head_resolved_rows("unit_entropy"), table_substr, column)
    for r in rows:
        ev = r.evidence[0] if isinstance(r.evidence, list) and r.evidence else {}
        return float(r.score), ev.get("detected_unit")
    return None


def _prove_unit_declaration_landing() -> None:
    """A unit teach makes the column's unit LAND (DAT-428): unit_entropy evidence
    ``detected_unit`` goes ``None`` -> the taught unit after the re-run.

    On this financial data unit_entropy already scores ~0 ("inferred_from_dimension" —
    the unit is resolvable from a sibling currency column), so the teach's observable is
    the EXPLICIT declaration landing on the column, not a score drop. The applier→reader
    loop is proven deterministically in the engine (test_overlay + test_typing_phase's
    TestApplyUnitOverrides); this is the end-to-end confirmation through real Temporal.
    """
    if not (DATA_DIR / _UNIT_STRATEGY).exists():
        pytest.skip(
            f"no data for {_UNIT_STRATEGY}; run `python -m calibration.runner {_UNIT_STRATEGY}`"
        )

    run = _load_run(_UNIT_STRATEGY)

    before = _unit_entropy_detected_unit(_UNIT_TABLE, _UNIT_COLUMN)
    if before is None:
        pytest.skip(f"unit_entropy did not fire on {_UNIT_TABLE}.{_UNIT_COLUMN} (not a measure?)")
    _, before_unit = before
    assert before_unit is None, (
        f"{_UNIT_TABLE}.{_UNIT_COLUMN} already has a declared unit {before_unit!r}; "
        "pick a column with no declared unit so the teach has something to land"
    )

    runner_mod.teach_unit_and_rerun(run, table=_UNIT_TABLE, column=_UNIT_COLUMN, unit=_TAUGHT_UNIT)

    after = _unit_entropy_detected_unit(_UNIT_TABLE, _UNIT_COLUMN)
    assert after is not None, "unit_entropy object vanished after the teach re-run"
    _, after_unit = after
    # The taught unit lands on the already-typed numeric column — the dead link
    # ("nothing writes overrides.units") is closed. Independent of type-pattern matching.
    assert after_unit == _TAUGHT_UNIT, (
        f"unit teach did not land: detected_unit {before_unit!r} -> {after_unit!r}"
    )


# ---------------------------------------------------------------------------
# Row: relationship confirm/keep (class 1 — persisted pre/post runs, no LLM)
# ---------------------------------------------------------------------------

_PairKey = frozenset[tuple[str, str]]


def _taught_pair_plan() -> dict[_PairKey, str]:
    """The teach protocol's deterministic verdict plan, re-derived from ground truth.

    Mirrors ``scripts/calibrate_teach_protocol.planned_verdicts``: the GENUINE
    labelled pairs sorted by child column, alternating ``confirm`` (→ the
    ``manual_curation`` witness) and ``keep`` (→ ``keeper_retention``).
    """
    emap = yaml.safe_load((DATA_DIR / _REL_STRATEGY / "entropy_map.yaml").read_text())
    genuine = sorted(
        (
            inj["parameters"]
            for inj in emap["injections"]
            if inj.get("injection_type") == "inject_relationship_pairs"
            and inj["parameters"]["label"] == "genuine"
        ),
        key=lambda p: str(p["child_column"]),
    )
    return {
        frozenset(
            {
                (str(p["child_table"]), str(p["child_column"])),
                (str(p["parent_table"]), str(p["parent_column"])),
            }
        ): ("manual_curation" if i % 2 == 0 else "keeper_retention")
        for i, p in enumerate(genuine)
    }


def _relationship_pools_by_run() -> tuple[list[str], dict[str, dict[_PairKey, tuple[float, float, frozenset[str]]]]]:
    """Per run (ordered by first write): pair → (pooled C, p_genuine, witness ids).

    Claim-row read (the ``calibrate_wave2_reliabilities`` surface): the persisted
    ``claim_witnesses`` rows ARE the pooling engine's production input — each row
    carries the witness's distribution and reliability — so re-pooling them per
    ``run_id`` reproduces each run's adjudication exactly.
    """
    from dataraum.entropy.db_models import ClaimWitnessRecord
    from dataraum.entropy.measurements.relationship_discovery import CLAIM_SPACE
    from dataraum.entropy.models import parse_relationship_target
    from dataraum.entropy.pooling import Witness, pool
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    runner_mod.bootstrap_engine()
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            table_names = {t.table_id: t.table_name for t in s.execute(select(Table)).scalars()}
            col_names = {
                c.column_id: (
                    table_names.get(c.table_id, "").split("__", 1)[-1],
                    c.column_name,
                )
                for c in s.execute(select(Column)).scalars()
            }
            # ALL runs' relationship witnesses (pre- AND post-teach), grouped by
            # run below — so NO current-head filter and no session axis (gone in
            # DAT-506): one eval workspace runs one strategy, so every relationship
            # witness row in it belongs to this strategy's pre/post-teach runs.
            records = (
                s.execute(
                    select(ClaimWitnessRecord).where(
                        ClaimWitnessRecord.detector_id == "relationship_discovery",
                    )
                )
                .scalars()
                .all()
            )
            rows = [
                (r.run_id, r.target, r.witness_id, dict(r.distribution or {}), r.reliability)
                for r in sorted(records, key=lambda r: r.computed_at)
            ]
    finally:
        mgr.close()

    run_order: list[str] = []
    grouped: dict[str, dict[_PairKey, list[tuple[str, dict[str, float], float]]]] = {}
    for run_id, target, witness_id, distribution, reliability in rows:
        if run_id is None:
            continue
        ids = parse_relationship_target(target)
        if ids is None:
            continue
        key: _PairKey = frozenset(col_names.get(i, ("?", "?")) for i in ids)
        if run_id not in grouped:
            grouped[run_id] = {}
            run_order.append(run_id)
        grouped[run_id].setdefault(key, []).append((witness_id, distribution, reliability))

    pooled: dict[str, dict[_PairKey, tuple[float, float, frozenset[str]]]] = {}
    for run_id, pairs in grouped.items():
        pooled[run_id] = {}
        for key, opinions in pairs.items():
            witnesses = tuple(
                Witness(
                    witness_id=witness_id,
                    distribution=tuple(distribution[label] for label in CLAIM_SPACE),
                    reliability=reliability,
                )
                for witness_id, distribution, reliability in opinions
            )
            result = pool(witnesses)
            pooled[run_id][key] = (
                result.conflict,
                result.posterior[CLAIM_SPACE.index("genuine")],
                frozenset(w for w, _, _ in opinions),
            )
    return run_order, pooled


def _prove_relationship_confirm_keep() -> None:
    """confirm/keep verdicts become the manual/keeper witnesses on the taught pairs.

    Closure here is the human verdict ENTERING the pool, not a conflict
    collapsing: the 11 taught pairs are GENUINE and already llm-confirmed, so
    the manual (confirm) and keeper (keep) witnesses JOIN an AGREEING pool. The
    observables, compared between the persisted pre-teach run (c56ff503…) and
    the post-teach re-run (e7b6589a…) of the same session:

    * the expected human witness is PRESENT post-teach and ABSENT pre-teach on
      every taught pair (the teach materialized as a witness, per-pair exact);
    * the posterior's genuine-lean STRENGTHENS (measured: per-pair p_genuine
      non-decreasing; mean 0.9656 → 1.0000);
    * pooled C on the taught pairs does not increase beyond the noise floor —
      asserted on the MEAN (measured 0.0313 → 0.0355): per-pair C moves with
      the LLM/overlap confidences, which shifted between runs independently of
      the teach (an untaught pair, journal_lines.entry_id, moved +0.07 with no
      verdict), so a per-pair bound would assert run noise, not the teach.

    Read entirely from persisted state (claim rows of both runs) — never kicks
    a pipeline; skips when the teach protocol has not run.
    """
    if not (DATA_DIR / _REL_STRATEGY).exists():
        pytest.skip(f"no data for {_REL_STRATEGY}; run the strategy + teach protocol first")
    sidecar = runner_mod.sidecar_path(_REL_STRATEGY)
    if not sidecar.exists():
        pytest.skip(f"no completed run for {_REL_STRATEGY} (missing {sidecar})")
    runner_mod.activate_workspace(_REL_STRATEGY)  # read this strategy's workspace (DAT-508)

    taught = _taught_pair_plan()
    assert taught, f"{_REL_STRATEGY} entropy_map lists no genuine relationship pairs"

    run_order, pooled = _relationship_pools_by_run()
    if len(run_order) < 2:
        pytest.skip(
            "teach protocol has not run for this session (single relationship_discovery "
            "run persisted) — run scripts/calibrate_teach_protocol.py first"
        )
    pre, post = pooled[run_order[0]], pooled[run_order[-1]]

    human = {"manual_curation", "keeper_retention"}
    pre_c, post_c, pre_p, post_p = [], [], [], []
    for key, expected_witness in sorted(taught.items(), key=lambda kv: sorted(kv[0])):
        name = " :: ".join(f"{t}.{c}" for t, c in sorted(key))
        assert key in pre and key in post, (
            f"taught pair {name} has no claim rows in both runs (pre={key in pre}, "
            f"post={key in post}) — the pair never entered the defined catalog"
        )
        c0, p0, witnesses0 = pre[key]
        c1, p1, witnesses1 = post[key]
        assert not (witnesses0 & human), (
            f"human witness {sorted(witnesses0 & human)} already present PRE-teach on {name}"
        )
        assert expected_witness in witnesses1, (
            f"the {expected_witness} witness did not materialize post-teach on {name} "
            f"(witnesses: {sorted(witnesses1)})"
        )
        assert p1 >= p0 - 1e-9, (
            f"genuine-lean weakened on taught pair {name}: p_genuine {p0:.3f} -> {p1:.3f}"
        )
        pre_c.append(c0)
        post_c.append(c1)
        pre_p.append(p0)
        post_p.append(p1)

    assert fmean(post_c) <= fmean(pre_c) + _DROP_MARGIN, (
        f"pooled C on taught pairs increased beyond the noise floor: "
        f"mean {fmean(pre_c):.4f} -> {fmean(post_c):.4f}"
    )
    assert fmean(post_p) >= fmean(pre_p), (
        f"genuine-lean did not strengthen: mean p_genuine {fmean(pre_p):.4f} -> {fmean(post_p):.4f}"
    )
    if fmean(pre_p) < 1.0 - 1e-9:
        assert fmean(post_p) > fmean(pre_p), (
            f"genuine-lean did not strengthen: mean p_genuine {fmean(pre_p):.4f} "
            f"-> {fmean(post_p):.4f}"
        )


# ---------------------------------------------------------------------------
# Row: validation / expected_formula (class 2 — one re-run on the derived corpus)
# ---------------------------------------------------------------------------


def _derived_value_state() -> tuple[float, str, list[dict[str, Any]]] | None:
    """Head-resolved (max score, raw table name, evidence entries) for the target column."""
    rows = _column_rows(
        _head_resolved_rows("derived_value"), _DERIVED_TABLE, _DERIVED_COLUMN
    )
    if not rows:
        return None
    # The detector-context table name — source-qualified, e.g. src_<digest>__formula_probes
    # — straight off the object's own target. load_declared_formula matches it exactly.
    raw_table = rows[0].target.removeprefix("column:").rsplit(".", 1)[0]
    entries: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r.evidence, list):
            entries.extend(e for e in r.evidence if isinstance(e, dict))
    return max(float(r.score) for r in rows), raw_table, entries


def _expected_formula_declared() -> bool:
    """Is an expected_formula declaration for the target column already taught?"""
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
    for r in rows:
        payload = r.payload or {}
        if payload.get("check_type") != "expected_formula":
            continue
        params = payload.get("parameters") or {}
        if str(params.get("column") or "") == _DERIVED_COLUMN and _DERIVED_TABLE in str(
            params.get("table") or ""
        ):
            return True
    return False


def _actual_formula_binary() -> str:
    """The wholesale target's ACTUAL formula, in the discovery's binary language.

    Reads the entropy_map's canonical ``actual_formula`` (e.g.
    ``ratio(inspection_subtotal,inspection_tax)``) and renders it as the binary
    arithmetic ``parse_formula`` accepts (``inspection_subtotal / inspection_tax``).
    Operand order is preserved — ratio/difference are not commutative.
    """
    from dataraum.entropy.measurements.derived_value import OPERATION_SYMBOL

    emap = yaml.safe_load((DATA_DIR / _DERIVED_STRATEGY / "entropy_map.yaml").read_text())
    params = next(
        inj["parameters"]
        for inj in emap["injections"]
        if inj.get("injection_type") == "inject_formula_divergence"
        and inj["target_column"] == _DERIVED_COLUMN
    )
    assert params["divergence_mode"] == "wholesale", (
        f"{_DERIVED_COLUMN} is no longer the wholesale target ({params['divergence_mode']})"
    )
    actual = str(params["actual_formula"])
    op, _, operands = actual.partition("(")
    left, _, right = operands.rstrip(")").partition(",")
    assert op in OPERATION_SYMBOL, f"actual formula {actual!r} is not a binary operation"
    return f"{left.strip()} {OPERATION_SYMBOL[op]} {right.strip()}"


def _prove_validation_expected_formula() -> None:
    """A validation (expected_formula) teach closes the derived_value identity conflict.

    The e2e proof of the engine-pinned closure shape
    (``test_matching_declaration_closes_the_column_score``): on the
    detection-derived-cal-v1 corpus, ``formula_probes.inspection_total`` is the
    WHOLESALE-divergent target — the rows follow ``inspection_subtotal /
    inspection_tax`` perfectly while the name advertises the sum, so pre-teach
    the head-resolved score is the pooled identity conflict (~0.83, above the
    recall band). The user declares the ACTUAL formula via the spec-shaped
    ``validation`` teach, addressed to the object's own raw table name (what
    ``load_declared_formula`` matches); on the same-session re-run the declared
    claim becomes the column's identity risk, the data and human witnesses
    agree there, and the head-resolved score drops below the band. The
    name-vs-data dispute survives in evidence as a naming finding — visible,
    not banding. Suggestion-consistency is asserted on the POST-teach evidence:
    the re-run executes the live engine, whose every derived_value evidence
    entry carries the ``validation``/``expected_formula`` suggestion the teach
    answered (the persisted PRE-teach run predates that routing, so the
    suggestion cannot be read from the frozen evidence).

    Idempotent re-execution: once the declaration overlay is taught, the
    pre-teach state no longer exists on the head — the row then asserts the
    persisted post-teach closure (score below the band, declared slot present)
    without driving another pipeline run.
    """
    if not (DATA_DIR / _DERIVED_STRATEGY).exists():
        pytest.skip(
            f"no data for {_DERIVED_STRATEGY}; run `python -m calibration.runner "
            f"{_DERIVED_STRATEGY}` first"
        )

    run = _load_run(_DERIVED_STRATEGY)
    already_taught = _expected_formula_declared()

    before: float | None = None
    if not already_taught:
        state = _derived_value_state()
        if state is None:
            pytest.skip(
                f"derived_value did not fire on {_DERIVED_TABLE}.{_DERIVED_COLUMN} "
                "in the baseline run"
            )
        before, raw_table, _ = state
        if before < DETECTION_THRESHOLD:
            pytest.skip(
                f"no banded identity conflict on {_DERIVED_TABLE}.{_DERIVED_COLUMN} "
                f"(score {before:.3f}) — the LLM hypothesis did not fire this run; "
                "nothing to close"
            )
        runner_mod.teach_validation_and_rerun(
            run,
            table=raw_table,
            column=_DERIVED_COLUMN,
            formula=_actual_formula_binary(),
        )

    state = _derived_value_state()
    assert state is not None, "derived_value object vanished after the teach re-run"
    after, _, entries = state
    declared_entries = [e for e in entries if e.get("declared")]
    assert declared_entries, (
        "the declaration did not land as a claim slot: no evidence entry has "
        f"declared=True on {_DERIVED_TABLE}.{_DERIVED_COLUMN}"
    )
    # Suggestion-consistency: the live engine's evidence carries the validation
    # teach suggestion this teach answered (always-emit, engine-pinned by
    # test_emitted_evidence_carries_the_validation_teach_suggestion).
    assert any(
        isinstance(e.get("teach_suggestion"), dict)
        and e["teach_suggestion"].get("type") == "validation"
        and e["teach_suggestion"].get("check") == "expected_formula"
        and e["teach_suggestion"].get("column") == _DERIVED_COLUMN
        for e in entries
    ), (
        f"post-teach derived_value evidence on {_DERIVED_COLUMN} carries no validation "
        "teach_suggestion — the teach routing contract broke"
    )
    # Teach-closure: the settled identity no longer bands the column. The band is
    # the recall surface's DETECTION_THRESHOLD the column exceeded pre-teach.
    assert after < DETECTION_THRESHOLD, (
        f"teach did not close the column score: {after:.3f} >= band {DETECTION_THRESHOLD}"
    )
    if before is not None:
        assert after < before - _DROP_MARGIN, (
            f"teach did not drop the score: {before:.3f} -> {after:.3f} "
            f"(delta {after - before:+.3f}, expected drop > {_DROP_MARGIN})"
        )


# ---------------------------------------------------------------------------
# Row: slice_conditional_null / expected_dependency (class 2 — one re-run, DAT-473)
# ---------------------------------------------------------------------------


def _slice_conditional_null_score(table_substr: str, column: str) -> float | None:
    """Head-resolved slice_conditional_null score (max bias-corrected V) for a column."""
    rows = _column_rows(
        _head_resolved_rows("slice_conditional_null"), table_substr, column
    )
    return max((float(r.score) for r in rows), default=None)


def _prove_slice_conditional_null_closure() -> None:
    """A document_business_rule teach closes a slice-conditional-null concentration (DAT-473).

    Runs detection-slice-null-v1 (nulls in journal_lines.debit concentrated in 1-2 cost
    centers), reads the head-resolved slice_conditional_null score, documents the
    (debit, cost_center) conditional-missingness rule via an ``expected_dependency`` overlay,
    RE-RUNS the same session, and asserts the score drops below the band: a documented
    dependency is expected structure, not entropy. Signed-delta grammar (ADR-0009).
    """
    if not (DATA_DIR / _SLICE_STRATEGY).exists():
        pytest.skip(
            f"no data for {_SLICE_STRATEGY}; run `python -m calibration.runner "
            f"{_SLICE_STRATEGY}` first"
        )

    run = _load_run(_SLICE_STRATEGY)

    before = _slice_conditional_null_score(_SLICE_TABLE, _SLICE_COLUMN)
    if before is None:
        pytest.skip(
            f"slice_conditional_null did not fire on {_SLICE_TABLE}.{_SLICE_COLUMN} "
            "in the baseline run"
        )
    if before < DETECTION_THRESHOLD:
        pytest.skip(
            f"no banded concentration on {_SLICE_TABLE}.{_SLICE_COLUMN} (score {before:.3f}) "
            "— the injection did not concentrate enough this run; nothing to close"
        )

    runner_mod.teach_slice_dependency_and_rerun(
        run,
        table=_SLICE_TABLE,
        column=_SLICE_COLUMN,
        slice_column=_SLICE_DIM,
        rule=f"{_SLICE_COLUMN} is intentionally blank for some {_SLICE_DIM} values (accrual-only)",
    )

    after = _slice_conditional_null_score(_SLICE_TABLE, _SLICE_COLUMN)
    assert after is not None, "slice_conditional_null object vanished after the teach re-run"
    # Teach-closure: the documented (column, slice) pair is excluded, so the concentration
    # is no longer entropy. The band is the recall surface's DETECTION_THRESHOLD.
    assert after < DETECTION_THRESHOLD, (
        f"teach did not close the column score: {after:.3f} >= band {DETECTION_THRESHOLD}"
    )
    assert after < before - _DROP_MARGIN, (
        f"teach did not drop the score: {before:.3f} -> {after:.3f} "
        f"(delta {after - before:+.3f}, expected drop > {_DROP_MARGIN})"
    )


# ---------------------------------------------------------------------------
# The harness — one row per teach type
# ---------------------------------------------------------------------------

# Class-3 rows: no honest closure scenario exists yet. The reasons are the
# coverage map — each states exactly what corpus member / assertion surface is
# missing. Faking any of these (string heuristics, deterministic overrides,
# induced-then-closed conflicts) is the Goodhart the harness exists to prevent.
_SKIP_ROWS: dict[str, str] = {
    "rebind": (
        "no honestly-closable rebind scenario in the current corpus (probed 2026-06-11 on "
        "the detection-stockflow-events-v1 session): the ignorance-dominant UNBOUND columns "
        "(measure_probes.ending_headcount, period_units) have no matching concept in the "
        "finance ontology to rebind to — a practitioner would need a concept teach first — "
        "and for the BOUND candidates (e.g. debt_position→current_liabilities@0.75) a rebind "
        "only nudges the LLM's grounding confidence: pure-measurement headroom is ΔU≈0.08 "
        "(U 0.610→0.526 at confidence 0.75→0.95), inside LLM run-to-run noise. Kill-gate "
        "verdict: no separation margin; needs a corpus member with an unbound column whose "
        "honest concept exists in the ontology"
    ),
    "concept": (
        "no assertion surface for a concept-definition teach yet: on the corpus's unbound "
        "columns (measure_probes.ending_headcount) the ontology_prior ABSTAINS pre-teach "
        "(U-dominant, C≈0), and defining a new concept moves no head-resolved score until a "
        "column binds to it (rebind) — needs an ignorance-closure (U-drop) assertion wired "
        "together with the rebind row, on a corpus member whose honest concept the teach "
        "would define"
    ),
    "type_pattern": (
        "needs a quarantine-pattern corpus member: the closure shape is a type_pattern teach "
        "that re-types quarantined values so the type_fidelity rate drops, but no typing cal "
        "session is persisted (detection-typing-v1 has no generated data/run) and its "
        "type-breaking injections corrupt values without a teachable custom pattern"
    ),
    "cycle": (
        "needs an operating-model assertion surface: a cycle teach upserts the cycle "
        "vocabulary (verticals/<v>/cycles.yaml) consumed by the business_cycles phase, but "
        "no entropy object or readiness surface reads the cycle vocabulary back — there is "
        "nothing head-resolved to close yet"
    ),
    "metric": (
        "needs an operating-model assertion surface: a metric teach upserts a transformation "
        "graph (verticals/<v>/metrics) executed by the metrics phase via graph-agent SQL, "
        "but no entropy object reads the metric back — there is nothing head-resolved to "
        "close yet"
    ),
}

# The teach vocabulary: 9 applier-backed types (engine appliable_teach_types) +
# the relationship overlay family. Tier-3 rows (docker + Temporal + LLM) are
# marked ``llm`` per the suite convention. Each row names the strategy it rides
# so the DAT-797 scoping guard below can pin it to that strategy's own pass.
_ROWS = [
    pytest.param(_NULL_STRATEGY, _prove_null_value_closure, id="null_value", marks=pytest.mark.llm),
    pytest.param(
        _TB_STRATEGY, _prove_concept_property_closure, id="concept_property", marks=pytest.mark.llm
    ),
    pytest.param(_UNIT_STRATEGY, _prove_unit_declaration_landing, id="unit", marks=pytest.mark.llm),
    pytest.param(
        _DERIVED_STRATEGY, _prove_validation_expected_formula, id="validation", marks=pytest.mark.llm
    ),
    pytest.param(
        _SLICE_STRATEGY,
        _prove_slice_conditional_null_closure,
        id="slice_conditional_null",
        marks=pytest.mark.llm,
    ),
    pytest.param(_REL_STRATEGY, _prove_relationship_confirm_keep, id="relationship"),
] + [
    pytest.param(None, None, id=teach_type, marks=pytest.mark.skip(reason=reason))
    for teach_type, reason in _SKIP_ROWS.items()
]


@pytest.mark.parametrize(("strategy", "prove"), _ROWS)
def test_teach_closure(strategy: str, prove: Callable[[], None], strategy_name: str) -> None:
    """One row per teach type — the executable closure map of the teach vocabulary.

    DAT-797 scoping (senior-review finding): each row rides its OWN hardcoded
    strategy and runs only on that strategy's ``--strategy`` pass. Sidecars
    persist across runner invocations by design (per-strategy workspaces, no
    reset between strategies), so without this guard a row whose sidecar exists
    from an EARLIER batch re-fires its Tier-3 teach re-run (real Temporal + LLM)
    inside every OTHER strategy's assert pass — the same cross-strategy LLM-leak
    class as the sidecar fallback this cut removed (run-#2 forensics).
    """
    if strategy_name != strategy:
        pytest.skip(f"row rides {strategy!r} — runs on its own --strategy pass only (DAT-797)")
    prove()
