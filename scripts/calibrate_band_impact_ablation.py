"""DAT-540 — band-impact + outcome-prediction ablation for a {score}-weighted
loss-path detector (null_ratio, slice_conditional_null).

The eval gate for DAT-514 P5 (ADR-0013): a loss-path detector earns its place
only if its loss contribution **changes a readiness band that maps to a real
wrong/unsafe answer** — otherwise it is trivially-derivable context and should be
DEMOTED to an informative DirectSignal (off the loss path) or CUT.

This is the {score}-detector analogue of `scripts/calibrate_structural_ablation.py`
(which ablates a POOLED witness's reliability). null_ratio and slice_conditional_null
are NOT pooled — loss.yaml scores their raw [0,1] `obj.score` directly — so the
ablation lives one level up, at the **readiness rollup**, not the witness pool:

  * Arm A (baseline):  risk(column, intent) over ALL the column's loss objects.
  * Arm B (ablated):   the same rollup with the TARGET detector's object dropped
    (it still computed + persisted; it just contributes nothing to readiness).

Both arms use the engine's REAL rollup (`compute_loss_risk` = clamp01(Σ weight·value),
max across a column's objects) + the REAL banding (`LossConfig.band`), so this
measures the shipped readiness, not a reconstruction. Per column × intent we get a
band pair (A, B) ∈ {ready, investigate, blocked}².

Outcome-prediction read (the crux — does a band move map to a real wrong answer?):
the entropy_map says which columns carry THIS detector's injection (a genuine
defect) and which are clean. A band that is WORSE under A than under B is a "lift":

  * TRUE lift   — injected column: A reads investigate/blocked where B reads safer.
    The detector is the reason a genuinely-defective column is not waved through.
    This is the marginal value — a band that maps to a real wrong/unsafe answer.
  * FALSE lift  — clean column: the detector pushed a clean column off `ready`.
    An over-fire — readiness cost with no defect behind it.
  * REDUNDANT   — injected column where A == B though the detector DID score: some
    OTHER measurement already drives the same band. The detector is non-marginal
    here — trivially-derivable context, the DEMOTE signal.

Verdict (printed, evidence-first — the human records KEEP/DEMOTE/CUT in the catalog):
  * KEEP    — net TRUE lifts on injected columns that are NOT redundant, with few/no
    false lifts on clean.
  * DEMOTE  — injected-column bands are all redundant (covered by another
    measurement): change no band that matters → informative DirectSignal, off loss.
  * CUT     — false lifts on clean without compensating true lift, OR no band-level
    separation of injected from clean at all.

A score-separation sanity line (injected vs clean `obj.score`) is printed first as
the recall floor — if the detector cannot even separate the families on score, the
band question is moot (the recall discipline: injected > clean + margin).

PRINT-ONLY: reads ONE completed run's sidecar; no pipeline, no code change.

Graduated from the DAT-540 probe to a reusable calibrator (cf.
`scripts/calibrate_structural_ablation.py`): re-run it to band-impact-gate any
{score}-weighted loss-path detector under the DAT-514 P5 / ADR-0013 review.

Run:  uv run python scripts/calibrate_band_impact_ablation.py <detector> [strategy]
      detector  ∈ {null_ratio, slice_conditional_null}
      strategy  defaults per detector (detection-null-v1 / detection-slice-null-v1)
      note: null_ratio's injection family lives in detection-v1; slice in
      detection-slice-null-v1. Pass the strategy explicitly for null_ratio.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import yaml

# Reuse the canonical eval read paths (sidecar-backed, no pipeline trigger).
from calibration.conftest import DATA_DIR, _strip_source_prefix
from calibration.tools._runs import load_run, short

DETECTOR_DEFAULT_STRATEGY = {
    "null_ratio": "detection-null-v1",
    "slice_conditional_null": "detection-slice-null-v1",
}

_BAND_RANK = {"ready": 0, "investigate": 1, "blocked": 2}


@dataclass(frozen=True)
class ColumnBands:
    """One column's arm-A/arm-B bands per intent + whether the target scored it."""

    table: str
    column: str
    injected: bool
    target_score: float | None  # the target detector's obj.score (None → did not fire)
    a_bands: dict[str, str]  # intent → band with the target
    b_bands: dict[str, str]  # intent → band without the target
    # Per intent, the arm-B detector(s) that drive the band (the competing measurement
    # that makes the target REDUNDANT when A==B): intent → [(detector_id, risk), …].
    b_drivers: dict[str, list[tuple[str, float]]]

    def lift_intents(self) -> list[str]:
        """Intents where the target makes the band WORSE (A ranks above B)."""
        return [
            i for i in self.a_bands
            if _BAND_RANK[self.a_bands[i]] > _BAND_RANK.get(self.b_bands.get(i, "ready"), 0)
        ]


def _injected_columns(strategy: str, detector: str) -> set[tuple[str, str]]:
    """(table, column) the entropy_map marks as carrying THIS detector's injection."""
    emap = yaml.safe_load((DATA_DIR / strategy / "entropy_map.yaml").read_text())
    out: set[tuple[str, str]] = set()
    for inj in emap.get("injections", []):
        if inj.get("detector_id") != detector:
            continue
        table = inj["target_file"].replace(".csv", "")
        out.add((short(table), inj["target_column"]))
    return out


def _objects_by_column(strategy: str) -> tuple[dict[str, list[Any]], dict[str, tuple[str, str]]]:
    """Head-resolved EntropyObjects grouped by `column:` target → list[EntropyObject].

    Mirrors `conftest._assemble_readiness`'s object reconstruction (DAT-447/506/508
    head resolution), but keeps the objects grouped so the target detector can be
    ablated out before the rollup.
    """
    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.entropy.models import EntropyObject
    from dataraum.storage import Column, Table
    from sqlalchemy import select

    from calibration.conftest import _head_resolved_entropy_rows
    from calibration.runner import bootstrap_engine

    bootstrap_engine()
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as session:
            records = _head_resolved_entropy_rows(session)
            by_target: dict[str, list[Any]] = defaultdict(list)
            for r in records:
                if not str(r.target).startswith("column:"):
                    continue
                by_target[r.target].append(
                    EntropyObject(
                        object_id=r.object_id,
                        layer=r.layer,
                        dimension=r.dimension,
                        sub_dimension=r.sub_dimension,
                        target=r.target,
                        score=r.score,
                        evidence=r.evidence if isinstance(r.evidence, list) else [],
                        detector_id=r.detector_id,
                    )
                )
            table_names = {t.table_id: t.table_name for t in session.execute(select(Table)).scalars()}
            col_names = {
                c.column_id: (table_names.get(c.table_id, ""), c.column_name)
                for c in session.execute(select(Column)).scalars()
            }
    finally:
        mgr.close()
    return by_target, col_names


def _bands(objects: list[Any], config: Any) -> dict[str, str]:
    """Per-intent band for a set of objects via the engine's real loss rollup."""
    from dataraum.entropy.loss import compute_loss_risk

    risk = compute_loss_risk(objects, config)
    return {intent: config.band(r) for intent, r in risk.items()}


def _intent_drivers(objects: list[Any], config: Any) -> dict[str, list[tuple[str, float]]]:
    """Per intent, each object's own risk contribution, sorted worst-first.

    Names WHO drives a column's band — the competing measurement that makes the
    target redundant. Uses the engine's per-object rollup so the numbers match
    `compute_loss_risk` (which takes the max across these).
    """
    from dataraum.entropy.loss import loss_risk_for_object

    per_intent: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for obj in objects:
        for intent, risk in loss_risk_for_object(obj, config).items():
            per_intent[intent].append((obj.detector_id, risk))
    return {i: sorted(v, key=lambda kv: -kv[1]) for i, v in per_intent.items()}


def _resolve(strategy: str, detector: str) -> list[ColumnBands]:
    from dataraum.entropy.loss import get_loss_config

    config = get_loss_config()
    by_target, _col_names = _objects_by_column(strategy)
    injected = _injected_columns(strategy, detector)

    rows: list[ColumnBands] = []
    for target, objects in sorted(by_target.items()):
        ref = target.removeprefix("column:")
        if "." not in ref:
            continue
        table, column = ref.split(".", 1)
        table = _strip_source_prefix(table)
        ablated = [o for o in objects if o.detector_id != detector]
        target_obj = next((o for o in objects if o.detector_id == detector), None)
        a_bands = _bands(objects, config)
        b_bands = _bands(ablated, config)
        # Only intents the loss table actually emits for these objects (a column with
        # no loss objects yields {} — skip it; it has no band to move).
        if not a_bands:
            continue
        rows.append(
            ColumnBands(
                table=table,
                column=column,
                injected=(table, column) in injected,
                target_score=(target_obj.score if target_obj else None),
                a_bands=a_bands,
                b_bands=b_bands,
                b_drivers=_intent_drivers(ablated, config),
            )
        )
    return rows


def _score_separation(rows: list[ColumnBands]) -> None:
    inj = [r.target_score for r in rows if r.injected and r.target_score is not None]
    cln = [r.target_score for r in rows if not r.injected and r.target_score is not None]
    print("## Score separation (the recall floor — must hold before the band question)")
    if not inj:
        print("   !! NO injected column carries a target score — detector never fired on its "
              "own injection. Score-level miss; band ablation is moot.\n")
        return
    inj_max = max(inj)
    cln_max = max(cln) if cln else 0.0
    print(f"   injected scores (n={len(inj)}): max={inj_max:.3f}  mean={sum(inj) / len(inj):.3f}")
    print(f"   clean    scores (n={len(cln)}): max={cln_max:.3f}  "
          f"mean={(sum(cln) / len(cln)) if cln else 0.0:.3f}")
    print(f"   separation margin (inj_max − clean_max) = {inj_max - cln_max:+.3f}"
          f"  {'(separates)' if inj_max - cln_max > 0 else '(NO separation — recall fails)'}\n")


def _print_bands(rows: list[ColumnBands], detector: str) -> None:
    intents = sorted({i for r in rows for i in r.a_bands})
    print(f"## Per-column band impact (A = with {detector}, B = ablated)")
    print(f"   {'column':28s} {'inj':4s} {'score':6s}  " +
          "  ".join(f"{i.replace('_intent', ''):>22s}" for i in intents))
    for r in sorted(rows, key=lambda x: (not x.injected, x.column)):
        cells = []
        for i in intents:
            a, b = r.a_bands.get(i, "—"), r.b_bands.get(i, "—")
            mark = "→" if a != b else " "
            cells.append(f"{b:>10s}{mark}{a:<10s}")
        score = f"{r.target_score:.2f}" if r.target_score is not None else "  —"
        print(f"   {r.column:28s} {'INJ' if r.injected else 'clr':4s} {score:6s}  " + "  ".join(cells))
    print()


def _print_verdict(rows: list[ColumnBands], detector: str) -> None:
    true_lifts: list[tuple[ColumnBands, list[str]]] = []
    false_lifts: list[tuple[ColumnBands, list[str]]] = []
    redundant: list[ColumnBands] = []
    for r in rows:
        lifts = r.lift_intents()
        if lifts and r.injected:
            true_lifts.append((r, lifts))
        elif lifts and not r.injected:
            false_lifts.append((r, lifts))
        elif r.injected and r.target_score and not lifts:
            # Detector scored this injected column but moved NO band → another
            # measurement already drives it (or the score is band-immaterial).
            redundant.append(r)

    print("## Band-impact tally")
    print(f"   TRUE  lifts (injected, band worse WITH detector): {len(true_lifts)}")
    for r, lifts in true_lifts:
        print(f"      ★ {r.column}: {', '.join(f'{i}={r.b_bands.get(i, 'ready')}→{r.a_bands[i]}' for i in lifts)} "
              f"(score {r.target_score:.2f})")
    print(f"   FALSE lifts (clean, over-fire):                   {len(false_lifts)}")
    for r, lifts in false_lifts:
        print(f"      !! {r.column}: {', '.join(f'{i}={r.b_bands.get(i, 'ready')}→{r.a_bands[i]}' for i in lifts)} "
              f"(score {r.target_score:.2f})")
    print(f"   REDUNDANT (injected, scored, NO band move):       {len(redundant)}")
    for r in redundant:
        # Name the competing measurement that already drives the worst injected intent.
        worst = max(r.a_bands, key=lambda i: _BAND_RANK[r.a_bands[i]])
        drivers = [f"{d}={rk:.2f}" for d, rk in r.b_drivers.get(worst, [])[:3] if rk > 0]
        print(f"      ∅ {r.column} (score {r.target_score:.2f}) — {worst}={r.a_bands[worst]} already set by: "
              f"{', '.join(drivers) or '(no other loss object — band is from the target alone?)'}")
    print()

    print("## VERDICT READ (evidence — the human records KEEP/DEMOTE/CUT in the catalog)")
    if not true_lifts and not false_lifts:
        print(f"   → {detector}: NO band-level separation (injected==clean at the band). "
              "Trivially-derivable context — DEMOTE/CUT candidate.")
    elif true_lifts and not false_lifts:
        print(f"   → {detector}: marginal value PROVEN — {len(true_lifts)} injected column(s) "
              "reach investigate/blocked ONLY because of this detector, none on clean. KEEP.")
    elif true_lifts and false_lifts:
        print(f"   → {detector}: MIXED — {len(true_lifts)} true vs {len(false_lifts)} false lift(s). "
              "Tune (the false lifts are over-fires) or weigh the trade — not a clean KEEP/CUT.")
    else:
        print(f"   → {detector}: false lifts ONLY ({len(false_lifts)}) — over-fires on clean with no "
              "injected-column band rescue. CUT candidate.")
    if redundant:
        print(f"   (plus {len(redundant)} injected column(s) where the detector is REDUNDANT — "
              "another measurement already sets the band; demote-leaning evidence.)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("detector", choices=sorted(DETECTOR_DEFAULT_STRATEGY))
    parser.add_argument("strategy", nargs="?", default=None)
    args = parser.parse_args()
    strategy = args.strategy or DETECTOR_DEFAULT_STRATEGY[args.detector]

    load_run(strategy)  # activates the strategy's workspace; fails loud if no sidecar
    print(f"# DAT-540 band-impact ablation — detector={args.detector}  strategy={strategy}\n")
    rows = _resolve(strategy, args.detector)
    if not rows:
        print("!! no column-scoped loss objects in this run — nothing to ablate "
              "(did the pipeline complete? check output/<strategy>/worker.log).")
        return
    _score_separation(rows)
    _print_bands(rows, args.detector)
    _print_verdict(rows, args.detector)


if __name__ == "__main__":
    main()
