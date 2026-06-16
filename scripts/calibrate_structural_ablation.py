"""Measure the MARGINAL VALUE of the temporal_behavior structural_reconciliation
witness — an A/B ablation on the resolved stock/flow label (DAT-491).

Distinct from `calibrate_wave2_reliabilities.py structural`, which measures the
witness's per-vote reliability (how accurate it is WHEN it fires). This rig asks
the orthogonal question: is the witness NON-REDUNDANT — does the slice→temporal→
lineage substrate change any verdict that ontology_prior + llm_claim already get
right? It pools the resolved label and scores the OUTPUT, not each witness.

Method (offline re-pool over ONE pipeline run's persisted witnesses — the
`calibrate_wave2` / `test_teach_cycle` surface): the persisted `claim_witnesses`
rows ARE the pooling engine's production input, each carrying a witness's
distribution + reliability. Re-pooling them with two weight sets reproduces
`measure_temporal_behavior` exactly (the witness distributions are
reliability-independent — only the pool weight changes):

  * Arm A (baseline):  structural_reconciliation reliability = 0.889
  * Arm B (ablated):   structural_reconciliation reliability = 0.0   (the row is
    kept and still opines, but contributes zero pool weight — the clean ablation)

ontology_prior=0.762, llm_claim=0.838 in both arms (the shipped values, imposed
explicitly so the ablation is exactly A vs B regardless of runtime threading; the
persisted r is printed as a sanity check). Per column: pool(witnesses) →
resolved_behaviour → label ∈ {point_in_time, additive, None}, compared to the
entropy_map ground truth (None excluded from accuracy, counted separately).

The discriminating regime is BACKED × AMBIGUOUS: a column the structural witness
can speak on (event-backed) whose name misleads the readers (ambiguous). Only
there can structural change the verdict. The three corpora:

  * detection-stockflow-events-ambiguous-v1 — the 2x2 factorial: backing CROSSED
    with ambiguous names. The only corpus that populates the decisive cell.
  * detection-stockflow-events-v1 — backed but CLEAR names: structural fires but
    is redundant (name-pair already correct). A==B expected (control: redundant).
  * detection-stockflow-cal-v1 — ambiguous but UNBACKED: structural abstains
    everywhere. A==B expected (negative control: silent). Pass --control.

PRINT-ONLY (no run, no code change). E2E dependency (lane F1): the slicing agent
must pick series_id on both probe tables, else lineage is empty and structural
abstains — the rig flags that as an artifact, not a finding.

Run:  uv run python scripts/calibrate_structural_ablation.py [strategy] [--control]
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import yaml

from calibration.conftest import DATA_DIR
from calibration.tools._runs import load_run, short, workspace_session

# The two arms, imposed explicitly (the protocol's reliabilities.yaml knob).
RELIABILITIES_A = {"ontology_prior": 0.762, "llm_claim": 0.838, "structural_reconciliation": 0.889}
RELIABILITIES_B = {"ontology_prior": 0.762, "llm_claim": 0.838, "structural_reconciliation": 0.0}

STRATA_ORDER = ("backed_reconciling", "backed_broken", "unbacked_stock", "flow")
BACKED_STRATA = ("backed_reconciling", "backed_broken")  # where structural can fire
_EPS = 1e-6

# column → {witness_id: (distribution over (stock, flow), persisted reliability)}.
Opinions = dict[str, tuple[tuple[float, float], float]]


def behaviour_truth(true_behavior: str) -> str:
    """Ground-truth resolved-label vocabulary: stock→point_in_time, flow→additive."""
    return "point_in_time" if true_behavior == "stock" else "additive"


def stockflow_stratum(params: dict[str, Any]) -> str:
    """The four ground-truth strata, from the entropy_map injection parameters."""
    if params["true_behavior"] == "flow":
        return "flow"
    if params.get("backed") and params.get("reconciles"):
        return "backed_reconciling"
    if params.get("backed"):
        return "backed_broken"
    return "unbacked_stock"


def ground_truth(strategy: str) -> dict[str, dict[str, Any]]:
    """Per probe column → its injection parameters (true_behavior, backed, …)."""
    emap = yaml.safe_load((DATA_DIR / strategy / "entropy_map.yaml").read_text())
    out: dict[str, dict[str, Any]] = {}
    for inj in emap["injections"]:
        if inj.get("injection_type") != "inject_stock_flow_probes":
            continue
        out[inj["target_column"]] = dict(inj["parameters"])
    return out


def load_witnesses(strategy: str) -> tuple[dict[str, Opinions], dict[str, tuple[str, str]], str | None]:
    """Per probe column → its persisted temporal witnesses, the lineage map, run_id.

    Mirrors `test_teach_cycle._relationship_pools_by_run`: read ALL
    temporal_behavior `claim_witnesses` (post-DAT-506 there is no session axis —
    one strategy per workspace), group by run_id, and pick the begin_session run
    (the one carrying structural rows, where the catalog-head adjudication runs).
    """
    from dataraum.entropy.db_models import ClaimWitnessRecord
    from dataraum.entropy.measurements.temporal_behavior import CLAIM_SPACE
    from sqlalchemy import select

    with workspace_session() as session:
        records = (
            session.execute(
                select(ClaimWitnessRecord).where(ClaimWitnessRecord.detector_id == "temporal_behavior")
            )
            .scalars()
            .all()
        )
        rows = [
            (r.run_id, r.claim_field, r.witness_id, dict(r.distribution or {}), float(r.reliability))
            for r in records
        ]
        lineage = _load_lineage(session)

    by_run: dict[str, dict[str, Opinions]] = defaultdict(lambda: defaultdict(dict))
    for run_id, claim_field, witness_id, dist, reliability in rows:
        if run_id is None or not claim_field.startswith("temporal_behavior:"):
            continue
        ref = claim_field.split(":", 1)[1]
        if "." not in ref:
            continue
        table, column = ref.split(".", 1)
        if short(table) != "measure_probes" or "stock" not in dist or "flow" not in dist:
            continue
        distribution = (float(dist[CLAIM_SPACE[0]]), float(dist[CLAIM_SPACE[1]]))
        by_run[run_id][column][witness_id] = (distribution, reliability)

    if not by_run:
        return {}, lineage, None

    def structural_count(run_id: str) -> int:
        return sum(1 for col in by_run[run_id].values() if "structural_reconciliation" in col)

    chosen = max(by_run, key=lambda r: (structural_count(r), len(by_run[r])))
    return by_run[chosen], lineage, chosen


def _load_lineage(session: Any) -> dict[str, tuple[str, str]]:
    """Measure column name → (pattern, match_rate) for every reconciled lineage row."""
    from dataraum.analysis.lineage.db_models import MeasureAggregationLineage
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    table_names = {t.table_id: t.table_name for t in session.execute(select(Table)).scalars()}
    col_names = {
        c.column_id: (short(table_names.get(c.table_id, "")), c.column_name)
        for c in session.execute(select(Column)).scalars()
    }
    out: dict[str, tuple[str, str]] = {}
    for row in session.execute(select(MeasureAggregationLineage)).scalars():
        _table, column = col_names.get(row.measure_column_id, ("?", "?"))
        out[column] = (row.pattern, f"{row.match_rate:.3f}")
    return out


def repool(opinions: Opinions, reliabilities: dict[str, float]) -> str | None:
    """Re-pool one column's persisted witnesses under an arm's weights → label.

    Uses the engine's real `pool()` + `resolved_behaviour()`; the arm's
    reliability overrides the persisted weight per witness_id (an absent witness
    weights 0). Returns the resolved label ∈ {point_in_time, additive, None}.
    """
    from dataraum.entropy.measurements.temporal_behavior import _has_opinion, resolved_behaviour
    from dataraum.entropy.pooling import Witness, pool

    witnesses = [
        w
        for witness_id, (dist, _r) in opinions.items()
        if _has_opinion(w := Witness(witness_id=witness_id, distribution=dist, reliability=reliabilities.get(witness_id, 0.0)))
    ]
    label, _contested = resolved_behaviour(pool(tuple(witnesses)))
    return label


def _lean(dist: tuple[float, float]) -> int:
    """Sign of a witness's lean: +1 stock, -1 flow, 0 abstain."""
    delta = dist[0] - 0.5
    return 0 if abs(delta) <= _EPS else (1 if delta > 0 else -1)


@dataclass(frozen=True)
class ColumnResult:
    """One probe column's ground truth + both arms' resolved labels."""

    column: str
    params: dict[str, Any]
    truth: str
    a_label: str | None
    b_label: str | None
    ont_lean: int
    llm_lean: int
    opinions: Opinions | None  # None → no temporal witnesses at all for this column

    @property
    def stratum(self) -> str:
        return stockflow_stratum(self.params)

    @property
    def ambiguous(self) -> bool:
        return bool(self.params.get("ambiguous"))


def _resolve_all(truth: dict[str, dict[str, Any]], columns: dict[str, Opinions]) -> list[ColumnResult]:
    results: list[ColumnResult] = []
    for column, params in sorted(truth.items()):
        gt = behaviour_truth(params["true_behavior"])
        opinions = columns.get(column)
        if opinions is None:
            results.append(ColumnResult(column, params, gt, None, None, 0, 0, None))
            continue
        ont = opinions.get("ontology_prior", ((0.5, 0.5), 0.0))[0]
        llm = opinions.get("llm_claim", ((0.5, 0.5), 0.0))[0]
        results.append(
            ColumnResult(
                column,
                params,
                gt,
                repool(opinions, RELIABILITIES_A),
                repool(opinions, RELIABILITIES_B),
                _lean(ont),
                _lean(llm),
                opinions,
            )
        )
    return results


def _accuracy(subset: list[ColumnResult], arm_a: bool) -> tuple[int, int, int]:
    """(correct, decided, abstained) for one arm over a subset; None excluded."""
    correct = decided = abstained = 0
    for r in subset:
        label = r.a_label if arm_a else r.b_label
        if r.opinions is None or label is None:
            abstained += 1
            continue
        decided += 1
        correct += int(label == r.truth)
    return correct, decided, abstained


def _fmt_acc(c: int, d: int) -> str:
    return f"{c}/{d}={c / d:.0%}" if d else "—"


def _print_header(strategy: str, truth: dict[str, dict[str, Any]], columns: dict[str, Opinions],
                  lineage: dict[str, tuple[str, str]], run_id: str | None,
                  control: bool) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]], int]:
    probe_lineage = {c: v for c, v in lineage.items() if c in truth}
    other_lineage = {c: v for c, v in lineage.items() if c not in truth}
    n_strata = Counter(stockflow_stratum(p) for p in truth.values())
    persisted_r: dict[str, set[str]] = defaultdict(set)
    structural_opinions = 0
    for col in columns.values():
        for wid, (_d, r) in col.items():
            persisted_r[wid].add(f"{r:.3f}")
        structural_opinions += int("structural_reconciliation" in col)

    print(f"# structural_reconciliation marginal-value ablation — {strategy}")
    print(f"#   begin_session run_id: {run_id}")
    print(f"#   probe columns: {len(truth)} ground truth, {len(columns)} with temporal witnesses")
    print("#   strata: " + ", ".join(f"{k}={n_strata[k]}" for k in STRATA_ORDER))
    print(f"#   lineage on PROBE columns ({len(probe_lineage)}): {probe_lineage}")
    print(f"#   lineage on finance-scaffold tables ({len(other_lineage)}, excluded): {other_lineage}")
    print(f"#   persisted reliabilities: {dict(persisted_r)}")
    print(f"#   columns where structural_reconciliation opined: {structural_opinions}\n")

    if structural_opinions == 0 and not control:
        print(
            "!! structural_reconciliation ABSTAINED on every column. For a backed corpus "
            "this means the lineage substrate produced nothing — likely the slicing agent "
            "missed series_id on a probe table (lane-F1). A==B here is an ARTIFACT — re-run "
            "the pipeline and check output/<strategy>/worker.log slice dims.\n"
        )
    return probe_lineage, other_lineage, structural_opinions


def _print_per_column(results: list[ColumnResult], probe_lineage: dict[str, tuple[str, str]]) -> None:
    print("## Per-column witness leans + A/B resolve")
    print(f"   {'column':24s} {'stratum':18s} {'amb':4s} {'truth':13s} {'ont':5s} {'llm':5s} "
          f"{'struct':16s} {'A':13s} {'B':13s}")
    leans = {1: "stock", -1: "flow", 0: "—"}
    for r in results:
        amb = "AMB" if r.ambiguous else "clr"
        if r.opinions is None:
            print(f"   {r.column:24s} {r.stratum:18s} {amb:4s} {r.truth:13s} (no witnesses)")
            continue
        struct = probe_lineage.get(r.column)
        struct_s = f"{struct[0]}@{struct[1]}" if struct else "abstain"
        a_s = f"{r.a_label}{'✓' if r.a_label == r.truth else '✗'}"
        b_s = f"{r.b_label}{'✓' if r.b_label == r.truth else '✗'}"
        print(f"   {r.column:24s} {r.stratum:18s} {amb:4s} {r.truth:13s} "
              f"{leans[r.ont_lean]:5s} {leans[r.llm_lean]:5s} {struct_s:16s} {a_s:13s} {b_s:13s}")
    print()


def _print_metrics(results: list[ColumnResult], probe_lineage: dict[str, tuple[str, str]],
                   truth: dict[str, dict[str, Any]], other_lineage: dict[str, tuple[str, str]],
                   structural_opinions: int, control: bool) -> None:
    backed = [r for r in results if r.stratum in BACKED_STRATA]
    print("## Metric 1 — resolved-label accuracy (None excluded, counted separately)")
    for name, subset in (("overall", results), (f"backed-only (n={len(backed)})", backed)):
        ac, ad, aab = _accuracy(subset, True)
        bc, bd, bab = _accuracy(subset, False)
        delta = (ac / ad - bc / bd) if ad and bd else 0.0
        print(f"   {name:24s}  A: {_fmt_acc(ac, ad):>12s} (abst {aab})   "
              f"B: {_fmt_acc(bc, bd):>12s} (abst {bab})   Δacc={delta:+.1%}")
    print()

    print("## Metric 1b — accuracy by name clarity (where the name-pair is expected to fail)")
    for clarity, want in (("clear", False), ("ambiguous", True)):
        subset = [r for r in results if r.ambiguous == want]
        ac, ad, _ = _accuracy(subset, True)
        bc, bd, _ = _accuracy(subset, False)
        print(f"   {clarity:10s} (n={len(subset)})  A: {_fmt_acc(ac, ad):>12s}   B: {_fmt_acc(bc, bd):>12s}")
    print()

    print("## DECISIVE CELL — backed × ambiguous (structural can fire AND names mislead)")
    decisive = [r for r in results if r.opinions is not None and r.params.get("backed") and r.ambiguous]
    if not decisive:
        print("   (no backed×ambiguous columns — this corpus does not populate the cell)")
    rescued = 0
    for r in decisive:
        struct = probe_lineage.get(r.column, ("—", "—"))
        a_ok, b_ok = r.a_label == r.truth, r.b_label == r.truth
        if a_ok and not b_ok:
            note, rescued = "★ STRUCTURAL RESCUES (A right, B wrong) — decisive tiebreaker", rescued + 1
        elif a_ok and b_ok:
            note = "name-pair already right (structural redundant here)"
        elif not a_ok and not b_ok:
            note = "both wrong (structural could not overcome the name-pair)"
        else:
            note = "!! A wrong, B right — structural HARMED"
        print(f"   {r.column:24s} [{r.stratum}] truth={r.truth} struct={struct[0]}@{struct[1]}  "
              f"A={r.a_label}({'OK' if a_ok else 'X'}) B={r.b_label}({'OK' if b_ok else 'X'})")
        print(f"      {note}")
    if decisive:
        print(f"\n   → structural rescued {rescued}/{len(decisive)} backed×ambiguous columns "
              f"(arm A correct where arm B was wrong) — the witness's marginal value.")
    print()

    print("## Metric 2 — flips (resolved label changes A→B)")
    flips: dict[str, list[ColumnResult]] = {"correct→wrong": [], "wrong→correct": [], "other": []}
    for r in results:
        if r.opinions is None or r.a_label == r.b_label:
            continue
        a_ok, b_ok = r.a_label == r.truth, r.b_label == r.truth
        key = "correct→wrong" if a_ok and not b_ok else "wrong→correct" if b_ok and not a_ok else "other"
        flips[key].append(r)
    for kind, items in flips.items():
        print(f"   {kind}: {len(items)}")
        for r in items:
            print(f"      {r.column}: A={r.a_label} B={r.b_label} (truth {r.truth}) [{r.stratum}]")
    print()

    print("## Metric 3 — contested tiebreak (ontology_prior vs llm_claim lean OPPOSITE)")
    contested = [r for r in results if r.opinions is not None and r.ont_lean and r.llm_lean
                 and r.ont_lean != r.llm_lean]
    for r in contested:
        has_struct = "structural_reconciliation" in (r.opinions or {})
        star = "★ structural is the decisive tiebreaker" if r.a_label == r.truth and r.b_label != r.truth else ""
        print(f"   {r.column} [{r.stratum}] truth={r.truth}  "
              f"ont={'stock' if r.ont_lean > 0 else 'flow'} vs llm={'stock' if r.llm_lean > 0 else 'flow'}  "
              f"structural={'YES' if has_struct else 'abstain'}")
        print(f"      → A={r.a_label} ({'OK' if r.a_label == r.truth else 'WRONG'})   "
              f"B={r.b_label} ({'OK' if r.b_label == r.truth else 'WRONG'})   {star}")
    if not contested:
        print("   (no columns where ontology_prior and llm_claim lean opposite)")
    print()

    print("## Metric 4 — coverage sanity (B must change nothing off the backed strata)")
    off_backed = [r for r in results if r.stratum not in BACKED_STRATA and r.opinions is not None]
    changed = [r for r in off_backed if r.a_label != r.b_label]
    print(f"   non-backed columns with witnesses: {len(off_backed)}; A≠B among them: {len(changed)}")
    for r in changed:
        print(f"      !! {r.column} [{r.stratum}] A={r.a_label} B={r.b_label} — UNEXPECTED")
    if control:
        ok = structural_opinions == 0
        print(f"   NEGATIVE CONTROL: structural opinions={structural_opinions} "
              f"({'PASS — abstains, A==B everywhere' if ok else 'FAIL — fired on a no-events corpus'})")
    print()

    n_measure, n_backed = len(truth), sum(1 for p in truth.values() if p.get("backed"))
    print("## Metric 5 — fire-rate (reconciled lineage on PROBE columns / probe columns)")
    print(f"   {len(probe_lineage)}/{n_measure} = {len(probe_lineage) / n_measure:.0%} of probe columns "
          f"reconciled ({len(probe_lineage)}/{n_backed} of the constructed-backed stocks). "
          f"Plus {len(other_lineage)} on finance-scaffold tables. Corpus is built to have backings — "
          f"production fire-rate is the unmeasured unknown.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("strategy", nargs="?", default="detection-stockflow-events-ambiguous-v1")
    parser.add_argument("--control", action="store_true",
                        help="Negative control: assert structural abstains and A==B everywhere.")
    args = parser.parse_args()

    load_run(args.strategy)  # activates this strategy's workspace
    truth = ground_truth(args.strategy)
    columns, lineage, run_id = load_witnesses(args.strategy)

    probe_lineage, other_lineage, structural_opinions = _print_header(
        args.strategy, truth, columns, lineage, run_id, args.control
    )
    results = _resolve_all(truth, columns)
    _print_per_column(results, probe_lineage)
    _print_metrics(results, probe_lineage, truth, other_lineage, structural_opinions, args.control)


if __name__ == "__main__":
    main()
