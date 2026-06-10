"""Measure the temporal_behavior witness reliabilities from the stock/flow corpus (DAT-450).

Archetype 2 for temporal_behavior. UNLIKE null_tokens (whose witnesses are deterministic
functions reconstructed offline), the ``llm_claim`` witness IS an LLM output — so the rig
reads the witnesses' verdicts from a real pipeline run over the generative stock/flow corpus
(detection-stockflow-cal-v1, which mixes a HARD ambiguous-name stratum into clear names),
scores each against the recorded ``true_behavior``, and reports the measured reliability
(Laplace-smoothed accuracy over opinionated votes — the same estimator as the null rig).

Two witnesses on the {stock, flow} claim:
  * ontology_prior — the bound concept's declared temporal_behavior (point_in_time→stock,
    additive→flow); abstains when no concept is bound.
  * llm_claim — the LLM's independent stock/flow read; abstains on unsure/absent.

Stratified clear vs ambiguous so the measured llm_claim reliability is FAITHFUL (the
ambiguous stratum is where the name-anchored LLM genuinely fails) rather than best-case.

Run:  uv run python scripts/calibrate_temporal_reliabilities.py            # measure + print
      uv run python scripts/calibrate_temporal_reliabilities.py --write    # + update reliabilities.yaml
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from calibration import runner as runner_mod
from calibration.conftest import DATA_DIR
from calibration.reliability_rig import WitnessVote, estimate_reliabilities

_STRATEGY = "detection-stockflow-cal-v1"

_PRIOR_PSTOCK = {"point_in_time": 1.0, "additive": 0.0}
_CLAIM_PSTOCK = {"stock": 1.0, "flow": 0.0}


@dataclass(frozen=True)
class ProbeRow:
    column: str
    is_stock: bool
    ambiguous: bool
    prior: str | None  # point_in_time / additive / None
    claim: str | None  # stock / flow / unsure / None


def _ground_truth() -> dict[str, tuple[bool, bool]]:
    """column → (is_stock, ambiguous), from the generated entropy_map."""
    emap = yaml.safe_load((DATA_DIR / _STRATEGY / "entropy_map.yaml").read_text())
    out: dict[str, tuple[bool, bool]] = {}
    for inj in emap["injections"]:
        if inj.get("detector_id") != "temporal_behavior":
            continue
        p = inj["parameters"]
        out[inj["target_column"]] = (p["true_behavior"] == "stock", bool(p.get("ambiguous", False)))
    return out


def _annotations(session_id: str) -> dict[str, tuple[str | None, str | None]]:
    """column → (ontology temporal_behavior prior, llm temporal_behavior_claim)."""
    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from sqlalchemy import text

    runner_mod.bootstrap_engine()
    mgr = ConnectionManager(ConnectionConfig.for_workspace())
    mgr.initialize()
    try:
        with mgr.session_scope() as s:
            rows = s.execute(
                text(
                    "SELECT c.column_name AS col, sa.temporal_behavior AS prior, "
                    "sa.temporal_behavior_claim AS claim "
                    "FROM semantic_annotations sa "
                    "JOIN columns c ON c.column_id = sa.column_id "
                    "JOIN tables t ON t.table_id = c.table_id "
                    "WHERE sa.session_id = :sid AND t.table_name LIKE '%measure_probes' "
                    "ORDER BY sa.annotated_at DESC"
                ),
                {"sid": session_id},
            ).all()
    finally:
        mgr.close()
    out: dict[str, tuple[str | None, str | None]] = {}
    for r in rows:
        out.setdefault(r.col, (r.prior, r.claim))  # most recent annotation per column
    return out


def _rows(session_id: str) -> list[ProbeRow]:
    truth = _ground_truth()
    ann = _annotations(session_id)
    return [
        ProbeRow(col, is_stock, ambiguous, *ann.get(col, (None, None)))
        for col, (is_stock, ambiguous) in truth.items()
        if col in ann
    ]


def _votes(rows: list[ProbeRow]) -> list[WitnessVote]:
    """One opinionated WitnessVote per (witness, column); abstaining witnesses dropped."""
    votes: list[WitnessVote] = []
    for r in rows:
        if r.prior in _PRIOR_PSTOCK:
            votes.append(WitnessVote("ontology_prior", _PRIOR_PSTOCK[r.prior], r.is_stock))
        if r.claim in _CLAIM_PSTOCK:
            votes.append(WitnessVote("llm_claim", _CLAIM_PSTOCK[r.claim], r.is_stock))
    return votes


def _accuracy(rows: list[ProbeRow], witness: str) -> tuple[float, int]:
    """Plain accuracy of one witness over its opinionated votes (for a stratum)."""
    correct = total = 0
    for r in rows:
        if witness == "ontology_prior" and r.prior in _PRIOR_PSTOCK:
            total += 1
            correct += (r.prior == "point_in_time") == r.is_stock
        if witness == "llm_claim" and r.claim in _CLAIM_PSTOCK:
            total += 1
            correct += (r.claim == "stock") == r.is_stock
    return (correct / total if total else 0.0), total


def main() -> None:
    if not (DATA_DIR / _STRATEGY).exists():
        raise SystemExit(
            f"no data for {_STRATEGY}; run `python -m calibration.runner {_STRATEGY}` first"
        )
    sidecar = runner_mod.sidecar_path(_STRATEGY)
    run = (
        runner_mod.CalibrationRun.from_json(sidecar.read_text())
        if sidecar.exists()
        else runner_mod.run_pipeline(_STRATEGY)
    )

    rows = _rows(run.session_id)
    clear = [r for r in rows if not r.ambiguous]
    hard = [r for r in rows if r.ambiguous]
    reliabilities = estimate_reliabilities(_votes(rows))

    print(
        f"# temporal_behavior reliability — corpus {_STRATEGY}, {len(rows)} probe columns "
        f"({len(clear)} clear / {len(hard)} ambiguous)\n"
    )
    for w in ("ontology_prior", "llm_claim"):
        r_all = reliabilities.get(w)
        acc_c, n_c = _accuracy(clear, w)
        acc_h, n_h = _accuracy(hard, w)
        shipped = f"{r_all:.3f}" if r_all is not None else "n/a (always abstained)"
        print(f"  {w}: reliability={shipped}")
        print(
            f"      clear accuracy={acc_c:.0%} (n={n_c})  |  ambiguous accuracy={acc_h:.0%} (n={n_h})"
        )
    # Print-only: the shipped artifact (dataraum-config/entropy/reliabilities.yaml) is
    # hand-curated WITH a provenance comment block (ADR-0009 source #1), which an automated
    # yaml dump would strip. Copy the values + the per-stratum provenance above into the
    # witnesses.temporal_behavior block by hand.
    print("\nApply the measured values + this provenance into reliabilities.yaml by hand.")


if __name__ == "__main__":
    main()
