"""Ground-first kill-gate for the stock/flow generative family (DAT-445 / DAT-450).

The temporal_behavior pooling math is already unit-proven, so this gate does NOT
re-derive a statistic. It decides BUILD vs CUT for the *family* by grounding two
things offline (ms, no LLM, no pipeline), driving the REAL measurement + the REAL
reliability estimator — no reimplemented witnesses:

  Q1 SEPARATION / INDEPENDENCE — does the family's construction make the two witnesses
     genuinely DIVERGE on a mislabel (prior wrong, LLM right) → high conflict C, while
     staying QUIET on a correct concept (prior == claim) → low C, by a margin? The e2e
     showed they can collapse to both-name-anchored (debit_balance: both 'stock'); the
     family must force real divergence via a MISLABELED CONCEPT (the prior is the
     concept's DECLARED behaviour — config — independent of the LLM's fresh read).

  Q2 RELIABILITY GENERALISATION — does the DAT-450 estimator (Laplace-smoothed accuracy
     on opinionated votes) recover NON-DEGENERATE, sensible per-witness reliabilities on
     this 2-witness, low-abstention family, and does the pooled posterior under the
     measured weights beat uniform? This is archetype-2 (rig generalises beyond
     null_tokens) in miniature.

The ONE thing not groundable offline is the LLM claim's true accuracy (needs the
pipeline). It is PARAMETERISED here and bracketed optimistic..pessimistic; kill-gate
v3 (LLM is name-anchored → a clear name yields the true read) is the prior, and the
e2e is the real measurement. If the family passes across the bracket, BUILD.

Run:  uv run python scripts/dat445_stockflow_gate.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from dataraum.entropy.measurements.temporal_behavior import (
    CLAIM_SPACE,
    measure_temporal_behavior,
)
from dataraum.entropy.pooling import Witness, pool

from calibration.reliability_rig import WitnessVote, estimate_reliabilities

_STOCK = CLAIM_SPACE.index("stock")

# Family design knobs (the corpus the generative family would realise).
_N = 800
_MISLABEL_RATE = 0.30  # fraction of samples whose CONCEPT is declared wrong
_CLEAR_RATE = 0.65  # fraction whose NAME clearly signals the true behaviour
_GROUNDING_CONF = 0.9  # how confidently the column is bound to its concept

# The one unknown — the LLM stock/flow claim's accuracy — bracketed. (clear, ambiguous):
#   clear  → P(LLM claims the TRUE behaviour); else it claims the opposite.
#   ambig  → P(claims TRUE); else 'unsure' (abstains).
_BRACKET = {"optimistic": (0.92, 0.70), "pessimistic": (0.78, 0.55)}

_TRUE_TO_BEHAVIOUR = {"stock": "point_in_time", "flow": "additive"}
_OPPOSITE_BEHAVIOUR = {"point_in_time": "additive", "additive": "point_in_time"}


@dataclass(frozen=True)
class Sample:
    is_stock: bool
    mislabeled: bool
    clear_name: bool


def _corpus(seed: int) -> list[Sample]:
    rng = random.Random(f"stockflow-gate:{seed}")
    out: list[Sample] = []
    for _ in range(_N):
        out.append(
            Sample(
                is_stock=rng.random() < 0.5,
                mislabeled=rng.random() < _MISLABEL_RATE,
                clear_name=rng.random() < _CLEAR_RATE,
            )
        )
    return out


def _llm_claim(
    s: Sample, rng: random.Random, p_clear: float, p_amb: float
) -> tuple[str | None, float]:
    """Model the LLM stock/flow read (the e2e measures the real thing; this brackets it)."""
    true = "stock" if s.is_stock else "flow"
    opp = "flow" if s.is_stock else "stock"
    if s.clear_name:
        return (true, 0.85) if rng.random() < p_clear else (opp, 0.7)
    # ambiguous name: either the true read (lower conf) or an honest abstain
    return (true, 0.55) if rng.random() < p_amb else ("unsure", 0.0)


def _adjudicate(s: Sample, rng: random.Random, p_clear: float, p_amb: float):  # noqa: ANN202
    true_behaviour = _TRUE_TO_BEHAVIOUR["stock" if s.is_stock else "flow"]
    ontology = _OPPOSITE_BEHAVIOUR[true_behaviour] if s.mislabeled else true_behaviour
    claim, claim_conf = _llm_claim(s, rng, p_clear, p_amb)
    adj = measure_temporal_behavior(
        "t",
        "c",
        ontology_behaviour=ontology,
        grounding_confidence=_GROUNDING_CONF,
        llm_claim=claim,
        llm_confidence=claim_conf,
    )
    return adj


def _pooled_p_stock(adj, reliabilities: dict[str, float] | None) -> float:  # noqa: ANN001
    if reliabilities is None:
        post = adj.result.posterior
        return post[_STOCK] if post else 0.5
    weighted = [
        Witness(w.witness_id, w.distribution, reliabilities.get(w.witness_id, w.reliability))
        for w in adj.witnesses
    ]
    res = pool(weighted)
    return res.posterior[_STOCK] if res.posterior else 0.5


def _run_bracket(name: str, p_clear: float, p_amb: float) -> dict:  # noqa: ANN001
    rng = random.Random(f"adj:{name}")
    rows = [(s, _adjudicate(s, rng, p_clear, p_amb)) for s in _corpus(7)]

    # Q1 separation: recall stratum = mislabeled concept + clear name (prior wrong, LLM right);
    # clean stratum = correct concept (witnesses should agree).
    recall_C = [adj.result.conflict for s, adj in rows if s.mislabeled and s.clear_name]
    clean_C = [adj.result.conflict for s, adj in rows if not s.mislabeled]
    recall_fire = sum(c > 0.3 for c in recall_C) / len(recall_C)
    clean_quiet = sum(c < 0.2 for c in clean_C) / len(clean_C)
    mean_recall_C = sum(recall_C) / len(recall_C)
    mean_clean_C = sum(clean_C) / len(clean_C)

    # Q2 reliability: each witness's P(stock) vote vs the true label → measured r.
    votes: list[WitnessVote] = []
    for s, adj in rows:
        for w in adj.witnesses:
            votes.append(WitnessVote(w.witness_id, w.distribution[_STOCK], s.is_stock))
    r = estimate_reliabilities(votes)

    # Pooled-posterior Brier (lower = better resolution) under measured vs uniform vs placeholder.
    def brier(rel: dict[str, float] | None) -> float:
        return sum(
            (_pooled_p_stock(adj, rel) - (1.0 if s.is_stock else 0.0)) ** 2 for s, adj in rows
        ) / len(rows)

    return {
        "name": name,
        "recall_fire": recall_fire,
        "clean_quiet": clean_quiet,
        "mean_recall_C": mean_recall_C,
        "mean_clean_C": mean_clean_C,
        "margin": mean_recall_C - mean_clean_C,
        "reliabilities": r,
        "brier_measured": brier(r),
        "brier_uniform": brier(dict.fromkeys(r, 0.5)),
        "brier_placeholder": brier({"ontology_prior": 0.7, "llm_claim": 0.6}),
    }


def main() -> None:
    print(
        f"# DAT-445 stock/flow family — ground-first gate (N={_N}, mislabel={_MISLABEL_RATE}, "
        f"clear={_CLEAR_RATE})\n"
    )
    results = [_run_bracket(n, *acc) for n, acc in _BRACKET.items()]

    passes = []
    for res in results:
        print(f"## {res['name']}  (LLM clear/ambig acc = {_BRACKET[res['name']]})")
        print(
            f"  Q1 separation: recall C̄={res['mean_recall_C']:.3f} fires>0.3 {res['recall_fire']:.0%}"
            f"  |  clean C̄={res['mean_clean_C']:.3f} quiet<0.2 {res['clean_quiet']:.0%}"
            f"  |  margin={res['margin']:+.3f}"
        )
        print(
            "  Q2 reliabilities (measured): "
            + ", ".join(f"{w}={v:.3f}" for w, v in sorted(res["reliabilities"].items()))
        )
        print(
            f"     pooled brier: measured={res['brier_measured']:.3f}  "
            f"uniform={res['brier_uniform']:.3f}  placeholder={res['brier_placeholder']:.3f}"
        )
        # SEPARATION is the family-design property: the mislabel and clean conflict
        # distributions are pulled apart (margin) and the model does not over-fire on
        # correct concepts (clean_quiet) at the calibrated level. recall_fire is NOT a
        # gate criterion — by construction a mislabel+clear case fires iff the LLM claims
        # the true behaviour, so recall_fire ≈ LLM clear-name accuracy, an LLM property
        # the e2e measures, not anything the family controls. It is reported, not gated.
        sep_ok = res["margin"] > 0.3 and res["clean_quiet"] >= 0.8
        rel_ok = len(res["reliabilities"]) == 2 and all(
            0.05 < v < 0.99 for v in res["reliabilities"].values()
        )
        brier_ok = res["brier_measured"] <= res["brier_uniform"] + 1e-9
        verdict = sep_ok and rel_ok and brier_ok
        passes.append(verdict)
        print(
            f"     → sep_ok={sep_ok} rel_ok={rel_ok} brier_ok={brier_ok}  "
            f"{'PASS' if verdict else 'FAIL'}  "
            f"(recall_fire {res['recall_fire']:.0%} ≈ LLM clear-name acc, reported not gated)\n"
        )

    if all(passes):
        print(
            "VERDICT: BUILD — the mislabel construction separates (prior wrong vs LLM right) "
            "across the LLM-accuracy bracket, and the estimator recovers non-degenerate weights "
            "that beat uniform. The one e2e-gated assumption: the LLM reads the true behaviour "
            "from a clear name (kill-gate v3 prior)."
        )
    else:
        print(
            "VERDICT: CUT / REDESIGN — the family does not separate or calibrate across the "
            "bracket; record why before any build."
        )


if __name__ == "__main__":
    main()
