"""Measure the wave-2 witness reliabilities from real calibration runs (DAT-450 wave 2).

One rig, three measurement adapters — the same archetype as
``calibrate_temporal_reliabilities.py``: read the PERSISTED per-witness opinions
(``claim_witnesses`` rows) of a completed pipeline run over a generative corpus,
score each opinion against the recorded ground truth (``entropy_map.yaml``), and
report the measured reliability (Laplace-smoothed accuracy over opinionated
votes — ``calibration.reliability_rig.estimate_reliabilities``).

Adapters:
  * structural   — detection-stockflow-events-v1: the ``structural_reconciliation``
                   witness of temporal_behavior (headline), plus ontology_prior /
                   llm_claim re-measured on the same fresh corpus (secondary).
  * derived      — detection-derived-cal-v1: formula_discovery / llm_hypothesis
                   on the {holds, fails} claim per canonical formula identity.
  * relationship — detection-relationship-cal-v1: value_overlap / llm_judgment on
                   the {genuine, spurious} claim per injected pair, from CLAIM ROWS
                   ONLY. The defined catalog (post-LLM confirmation) is the only
                   surface relationship witnesses vote on in production — candidate
                   rows are a generous structural list, never a measurement or
                   calibration surface (the DAT-405 boundary; relearned 2026-06-11
                   when a synthesized-from-candidates r was shipped and withdrawn).
                   Pairs the LLM rejected leave no claim rows: that is the COVERAGE
                   map, a finding about the SELECTOR, reported loudly, never voted.

Single-run assumption: calibration strategies run ONE detect pass per session.
If claim rows from multiple run_ids show up for the same (target, claim_field,
witness), the rig keeps the run_id with the most rows and says so.

Run:  uv run python scripts/calibrate_wave2_reliabilities.py structural
      uv run python scripts/calibrate_wave2_reliabilities.py derived
      uv run python scripts/calibrate_wave2_reliabilities.py relationship

PRINT-ONLY: the shipped artifact (dataraum-config/entropy/reliabilities.yaml) is
hand-curated with provenance comments (ADR-0009 source #1) — apply by hand.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import yaml

from calibration.conftest import DATA_DIR
from calibration.reliability_rig import WitnessVote, estimate_reliabilities
from calibration.tools._runs import load_run, short, workspace_session

# Opinionated = the persisted distribution differs from uniform by more than
# this. Engine detectors already drop exactly-uniform witnesses before
# persisting (their _OPINION_EPS is 1e-6), but a low-confidence lean (e.g. a
# 0.52/0.48 split) is still effectively an abstention for reliability purposes
# — mirroring the temporal rig, abstain rows are EXCLUDED from r but COUNTED.
OPINION_EPS = 0.05


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimRow:
    """One persisted witness opinion, decoded to P(first claim-space label)."""

    target: str
    claim_field: str
    witness_id: str
    p_first: float | None
    run_id: str | None


@dataclass(frozen=True)
class RigVote:
    """One witness's stance on one ground-truthed claim slot."""

    witness_id: str
    p_positive: float | None  # None / near-uniform = abstained
    label_positive: bool
    strata: tuple[str, ...]

    @property
    def opinionated(self) -> bool:
        return self.p_positive is not None and abs(self.p_positive - 0.5) > OPINION_EPS

    @property
    def correct(self) -> bool:
        return self.p_positive is not None and (self.p_positive > 0.5) == self.label_positive


def _p_first(distribution: Any, label0: str) -> float | None:
    """P(first claim-space label) from a persisted distribution.

    The engine persists ``WitnessClaim.distribution`` as a label→probability
    DICT (entropy/models.py); a positional array is accepted too in case an
    older row shape survives.
    """
    if isinstance(distribution, dict):
        value = distribution.get(label0)
        return None if value is None else float(value)
    if isinstance(distribution, list | tuple) and distribution:
        return float(distribution[0])
    return None


def _ground_truth_params(strategy: str, injection_type: str) -> list[dict[str, Any]]:
    """The injections' parameter dicts (+ target_column) from the entropy map."""
    emap = yaml.safe_load((DATA_DIR / strategy / "entropy_map.yaml").read_text())
    out: list[dict[str, Any]] = []
    for inj in emap["injections"]:
        if inj.get("injection_type") != injection_type:
            continue
        params = dict(inj["parameters"])
        params["target_column"] = inj["target_column"]
        out.append(params)
    return out


def _load_claim_rows(
    session: Any, session_id: str, detector_id: str, label0: str
) -> list[ClaimRow]:
    """This session's persisted witness opinions for one measurement.

    Enforces the single-run assumption: when the same (target, claim_field,
    witness) carries rows from multiple run_ids, keep the run with the most
    rows overall and say so (cal strategies have ONE detect pass per session).
    """
    from dataraum.entropy.db_models import ClaimWitnessRecord
    from sqlalchemy import select

    records = (
        session.execute(
            select(ClaimWitnessRecord).where(
                ClaimWitnessRecord.session_id == session_id,
                ClaimWitnessRecord.detector_id == detector_id,
            )
        )
        .scalars()
        .all()
    )
    rows = [
        ClaimRow(r.target, r.claim_field, r.witness_id, _p_first(r.distribution, label0), r.run_id)
        for r in records
    ]
    keys: dict[tuple[str, str, str], set[str | None]] = defaultdict(set)
    for row in rows:
        keys[(row.target, row.claim_field, row.witness_id)].add(row.run_id)
    duplicated = {k: v for k, v in keys.items() if len(v) > 1}
    if duplicated:
        run_counts = Counter(row.run_id for row in rows)
        head, head_n = run_counts.most_common(1)[0]
        print(
            f"NOTE: single-run assumption violated — {len(duplicated)} claim keys carry rows "
            f"from {len(run_counts)} run_ids; keeping run {head} ({head_n} rows)."
        )
        rows = [row for row in rows if row.run_id == head]
    return rows


def _column_names(session: Any) -> dict[str, tuple[str, str]]:
    """column_id → (table_name, column_name), the conftest mapping."""
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    table_names = {t.table_id: t.table_name for t in session.execute(select(Table)).scalars()}
    return {
        c.column_id: (table_names.get(c.table_id, ""), c.column_name)
        for c in session.execute(select(Column)).scalars()
    }


def _stratum_table(votes: Sequence[RigVote], witness_id: str, strata_order: Sequence[str]) -> None:
    """Print per-stratum n / abstained / accuracy-over-opinions for one witness."""
    for stratum in strata_order:
        in_stratum = [v for v in votes if v.witness_id == witness_id and stratum in v.strata]
        if not in_stratum:
            continue
        opined = [v for v in in_stratum if v.opinionated]
        correct = sum(1 for v in opined if v.correct)
        accuracy = f"{correct / len(opined):.0%}" if opined else "—"
        print(
            f"      {stratum}: n={len(in_stratum)} opined={len(opined)} "
            f"abstained={len(in_stratum) - len(opined)} accuracy={accuracy}"
        )


def _report_witness(
    votes: Sequence[RigVote],
    witness_id: str,
    reliabilities: dict[str, float],
    strata_order: Sequence[str],
    note: str = "",
) -> None:
    mine = [v for v in votes if v.witness_id == witness_id]
    opined = sum(1 for v in mine if v.opinionated)
    r_value = reliabilities.get(witness_id)
    shipped = f"{r_value:.3f}" if r_value is not None else "n/a (always abstained)"
    suffix = f"  [{note}]" if note else ""
    print(
        f"  {witness_id}: reliability={shipped} "
        f"(opinions={opined}, abstained={len(mine) - opined} of {len(mine)} slots){suffix}"
    )
    _stratum_table(votes, witness_id, strata_order)


def _estimate(votes: Sequence[RigVote]) -> dict[str, float]:
    """Laplace-smoothed accuracy over OPINIONATED votes, via the shared rig."""
    return estimate_reliabilities(
        WitnessVote(v.witness_id, v.p_positive, v.label_positive)
        for v in votes
        if v.opinionated and v.p_positive is not None
    )


# ---------------------------------------------------------------------------
# Adapter 1 — structural (temporal_behavior / structural_reconciliation)
# ---------------------------------------------------------------------------

_STRUCTURAL_STRATEGY = "detection-stockflow-events-v1"
_STRUCTURAL_WITNESSES = ("structural_reconciliation", "ontology_prior", "llm_claim")
_STOCKFLOW_STRATA = ("backed_reconciling", "backed_broken", "unbacked_stock", "flow")


def _stockflow_stratum(params: dict[str, Any]) -> str:
    if params["true_behavior"] == "flow":
        return "flow"
    if params.get("backed") and params.get("reconciles"):
        return "backed_reconciling"
    if params.get("backed"):
        return "backed_broken"
    return "unbacked_stock"


def _structural_diagnostics(session: Any, session_id: str) -> None:
    """Why the structural witness had nothing to say — which prerequisite failed.

    The lane's known e2e dependency: the slicing agent must pick ``series_id``
    as a slice dimension on BOTH probe tables for the ``aggregation_lineage``
    phase to reconcile anything (engine ``analysis/lineage/processor.py``).
    """
    from dataraum.analysis.lineage.db_models import MeasureAggregationLineage
    from dataraum.analysis.slicing.db_models import SliceDefinition
    from sqlalchemy import select

    col_names = _column_names(session)
    lineage = (
        session.execute(
            select(MeasureAggregationLineage).where(
                MeasureAggregationLineage.session_id == session_id
            )
        )
        .scalars()
        .all()
    )
    print(f"\n  diagnostic: {len(lineage)} measure_aggregation_lineage rows for this session")
    for row in lineage:
        table, column = col_names.get(row.measure_column_id, ("?", "?"))
        print(
            f"      {short(table)}.{column}: pattern={row.pattern} "
            f"match_rate={row.match_rate:.3f} dim={row.slice_dimension} "
            f"entities={row.n_entities_fired}/{row.n_entities}"
        )
    slice_defs = (
        session.execute(select(SliceDefinition).where(SliceDefinition.session_id == session_id))
        .scalars()
        .all()
    )
    dims_by_table: dict[str, set[str]] = defaultdict(set)
    for sd in slice_defs:
        table, column = col_names.get(sd.column_id, ("?", "?"))
        dims_by_table[short(table)].add(sd.column_name or column)
    for probe_table in ("measure_probes", "probe_events"):
        dims = sorted(dims_by_table.get(probe_table, set()))
        marker = "OK" if "series_id" in dims else "MISSING series_id"
        print(f"      slice dims on {probe_table}: {dims or ['NONE']} ({marker})")
    if not lineage:
        print(
            "      → no lineage rows: the aggregation_lineage phase reconciled nothing; "
            "if series_id is missing above, the slicing agent is the failed prerequisite."
        )


def run_structural() -> None:
    run = load_run(_STRUCTURAL_STRATEGY)
    truth = {
        p["target_column"]: p
        for p in _ground_truth_params(_STRUCTURAL_STRATEGY, "inject_stock_flow_probes")
    }

    with workspace_session() as session:
        rows = _load_claim_rows(session, run.session_id, "temporal_behavior", label0="stock")

        per_column: dict[str, dict[str, float | None]] = defaultdict(dict)
        for row in rows:
            if not row.claim_field.startswith("temporal_behavior:"):
                continue
            ref = row.claim_field.split(":", 1)[1]
            if "." not in ref:
                continue
            table, column = ref.split(".", 1)
            if short(table) != "measure_probes" or column not in truth:
                continue
            per_column[column][row.witness_id] = row.p_first

        votes: list[RigVote] = []
        for column, params in truth.items():
            label = params["true_behavior"] == "stock"
            strata = ("all", _stockflow_stratum(params))
            for witness_id in _STRUCTURAL_WITNESSES:
                votes.append(RigVote(witness_id, per_column[column].get(witness_id), label, strata))

        reliabilities = _estimate(votes)
        n_strata = Counter(_stockflow_stratum(p) for p in truth.values())
        print(
            f"# temporal_behavior wave-2 — corpus {_STRUCTURAL_STRATEGY}, "
            f"{len(truth)} probe columns "
            f"({', '.join(f'{k}={n_strata[k]}' for k in _STOCKFLOW_STRATA)})\n"
        )
        _report_witness(
            votes, "structural_reconciliation", reliabilities, _STOCKFLOW_STRATA, note="HEADLINE"
        )
        for witness_id in ("ontology_prior", "llm_claim"):
            _report_witness(
                votes,
                witness_id,
                reliabilities,
                _STOCKFLOW_STRATA,
                note="secondary — free re-measurement on a fresh corpus",
            )

        headline_opined = any(
            v.opinionated for v in votes if v.witness_id == "structural_reconciliation"
        )
        if not headline_opined:
            print("\n  structural_reconciliation abstained on EVERY probe column.")
        _structural_diagnostics(session, run.session_id)


# ---------------------------------------------------------------------------
# Adapter 2 — derived (derived_value / formula_discovery + llm_hypothesis)
# ---------------------------------------------------------------------------

_DERIVED_STRATEGY = "detection-derived-cal-v1"
_DERIVED_WITNESSES = ("formula_discovery", "llm_hypothesis")
_DERIVED_STRATA = (
    "mode_agree",
    "mode_wholesale",
    "mode_partial",
    "discoverable",
    "undiscoverable",
)


def _formula_truth_holds(formula: str, params: dict[str, Any]) -> bool:
    """Ground truth for one canonical formula identity on a labelled column.

    HOLDS iff the claim names the formula that actually governs the data:
    the named formula in agree mode, or the actual formula in wholesale mode.
    Partial rows, scaled actuals, and mismatched identities all FAIL.
    """
    mode = str(params["divergence_mode"])
    return (formula == str(params["named_formula"]) and mode == "agree") or (
        formula == str(params["actual_formula"]) and mode == "wholesale"
    )


def run_derived() -> None:
    run = load_run(_DERIVED_STRATEGY)
    truth = {
        p["target_column"]: p
        for p in _ground_truth_params(_DERIVED_STRATEGY, "inject_formula_divergence")
    }

    with workspace_session() as session:
        rows = _load_claim_rows(session, run.session_id, "derived_value", label0="holds")

    # Group opinions per claim slot (column, formula); collect unlabelled noise.
    slots: dict[tuple[str, str], dict[str, float | None]] = defaultdict(dict)
    unlabelled: Counter[str] = Counter()
    for row in rows:
        parts = row.claim_field.split(":", 2)
        if len(parts) != 3 or parts[0] != "derived_formula" or "." not in parts[1]:
            continue
        table, column = parts[1].split(".", 1)
        formula = parts[2]
        if short(table) != "formula_probes" or column not in truth:
            unlabelled[f"{short(table)}.{column}"] += 1
            continue
        slots[(column, formula)][row.witness_id] = row.p_first

    votes: list[RigVote] = []
    for (column, formula), opinions in slots.items():
        params = truth[column]
        label = _formula_truth_holds(formula, params)
        strata = (
            "all",
            f"mode_{params['divergence_mode']}",
            "discoverable" if params.get("discoverable") else "undiscoverable",
        )
        for witness_id in _DERIVED_WITNESSES:
            votes.append(RigVote(witness_id, opinions.get(witness_id), label, strata))

    reliabilities = _estimate(votes)
    n_holds = sum(1 for v in votes if v.witness_id == _DERIVED_WITNESSES[0] and v.label_positive)
    n_slots = len(slots)
    print(
        f"# derived_value wave-2 — corpus {_DERIVED_STRATEGY}, "
        f"{len(truth)} labelled columns, {n_slots} claim slots "
        f"({n_holds} HOLDS / {n_slots - n_holds} FAILS)\n"
    )
    for witness_id in _DERIVED_WITNESSES:
        _report_witness(votes, witness_id, reliabilities, _DERIVED_STRATA)
    labelled_no_rows = sorted(c for c in truth if not any(col == c for col, _ in slots))
    if labelled_no_rows:
        print(f"\n  labelled columns with NO claim rows (excluded): {labelled_no_rows}")
    if unlabelled:
        total = sum(unlabelled.values())
        print(
            f"\n  unlabelled-column claim rows (canonical tables' own formulas — "
            f"excluded from r): {total} rows on {len(unlabelled)} columns"
        )


# ---------------------------------------------------------------------------
# Adapter 3 — relationship (relationship_discovery / value_overlap + llm_judgment)
# ---------------------------------------------------------------------------

_REL_STRATEGY = "detection-relationship-cal-v1"
_REL_STRATA = ("genuine_clean", "genuine_broken", "spurious_overlap")

PairKey = frozenset[tuple[str, str]]


def _pair_key(params: dict[str, Any]) -> PairKey:
    return frozenset(
        {
            (params["child_table"], params["child_column"]),
            (params["parent_table"], params["parent_column"]),
        }
    )


def run_relationship() -> None:
    from dataraum.entropy.models import parse_relationship_target

    run = load_run(_REL_STRATEGY)
    pairs = _ground_truth_params(_REL_STRATEGY, "inject_relationship_pairs")

    with workspace_session() as session:
        rows = _load_claim_rows(session, run.session_id, "relationship_discovery", label0="genuine")
        col_names = _column_names(session)

    # Claim rows per direction-agnostic pair key.
    claims: dict[PairKey, dict[str, float | None]] = defaultdict(dict)
    for row in rows:
        ids = parse_relationship_target(row.target)
        if ids is None:
            continue
        endpoints: PairKey = frozenset(
            (short(table), column)
            for table, column in (col_names.get(col_id, ("", "")) for col_id in ids)
        )
        claims[endpoints][row.witness_id] = row.p_first

    votes: list[RigVote] = []
    covered: dict[str, list[str]] = defaultdict(list)
    uncovered: dict[str, list[str]] = defaultdict(list)
    for params in pairs:
        key = _pair_key(params)
        label = params["label"] == "genuine"
        stratum = str(params["stratum"])
        strata = ("all", stratum)
        name = f"{params['child_table']}.{params['child_column']}→{params['parent_column']}"
        if key in claims:
            covered[stratum].append(name)
            for witness_id in ("value_overlap", "llm_judgment"):
                votes.append(RigVote(witness_id, claims[key].get(witness_id), label, strata))
        else:
            # No claim rows: the pair never entered the defined catalog, so no
            # witness ever voted on it. Coverage only — NEVER a synthesized vote.
            uncovered[stratum].append(name)

    reliabilities = _estimate(votes)
    print(
        f"# relationship_discovery wave-2 — corpus {_REL_STRATEGY}, {len(pairs)} injected pairs\n"
    )
    print("  COVERAGE (lane F2's premise finding — LLM-rejected pairs leave no claim rows):")
    for stratum in _REL_STRATA:
        n_covered, n_uncovered = len(covered[stratum]), len(uncovered[stratum])
        print(f"      {stratum}: claim rows for {n_covered}/{n_covered + n_uncovered} pairs")
        for name in uncovered[stratum]:
            print(
                f"          uncovered: {name} (rejected/unconfirmed — selector finding, not voted)"
            )
    print()

    _report_witness(
        votes,
        "value_overlap",
        reliabilities,
        _REL_STRATA,
        note="claim rows only — the defined catalog (post-LLM) is the only surface "
        "this witness votes on in production",
    )
    _report_witness(
        votes,
        "llm_judgment",
        reliabilities,
        _REL_STRATA,
        note="claim rows only — conditional on the LLM having ACCEPTED the pair; "
        "rejections never reach the catalog, so false-rejects are invisible here",
    )
    print(
        "  manual_curation: UNMEASURABLE on this corpus — no teach actions in a "
        "calibration run; needs the teach protocol."
    )
    print(
        "  keeper_retention: UNMEASURABLE on this corpus — no keep overlays in a "
        "calibration run; needs the teach protocol."
    )


# ---------------------------------------------------------------------------


_ADAPTERS = {
    "structural": run_structural,
    "derived": run_derived,
    "relationship": run_relationship,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("measurement", choices=sorted(_ADAPTERS))
    args = parser.parse_args()
    _ADAPTERS[args.measurement]()
    # Print-only: the shipped artifact (dataraum-config/entropy/reliabilities.yaml)
    # is hand-curated WITH a provenance comment block (ADR-0009 source #1), which an
    # automated yaml dump would strip. Copy the values + the per-stratum provenance
    # above into the measurement's witness block by hand.
    print("\nApply the measured values + this provenance into reliabilities.yaml by hand.")


if __name__ == "__main__":
    main()
