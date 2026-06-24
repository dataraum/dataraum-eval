"""DAT-620 lane-1 scoring: per-value precision/recall, trap correctness, metric error.

All scores are computed per (seed, leg) and pooled over holdout seeds by the runner.
Relative/Goodhart-safe: the decision is the A-vs-B separation and the trap/metric
outcomes, never a tuned point threshold on one dataset.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from generate import Fixture


@dataclass
class LegScore:
    n_values: int = 0
    n_correct: int = 0
    class_total: dict[str, int] = field(default_factory=dict)
    class_correct: dict[str, int] = field(default_factory=dict)
    # failure mode per class: abstained (pred unmapped, not correct) = safe undercount;
    # mislabeled (pred a wrong concept) = dangerous, can corrupt the metric
    class_abstain: dict[str, int] = field(default_factory=dict)
    class_mislabel: dict[str, int] = field(default_factory=dict)
    # confusion for macro P/R over concept labels
    tp: dict[str, int] = field(default_factory=dict)
    fp: dict[str, int] = field(default_factory=dict)
    fn: dict[str, int] = field(default_factory=dict)
    # metric reconstruction
    gp_truth: float = 0.0
    gp_pred: float = 0.0

    def _bump(self, d: dict[str, int], k: str, n: int = 1) -> None:
        d[k] = d.get(k, 0) + n


def score(fixture: Fixture, predictions: dict[str, tuple[str, float]]) -> LegScore:
    s = LegScore()
    pred_revenue: list[str] = []
    pred_cogs: list[str] = []

    for value, (true_concept, klass) in fixture.oracle.items():
        pred_concept = predictions.get(value, ("unmapped", 0.0))[0]
        s.n_values += 1
        s._bump(s.class_total, klass)
        if pred_concept == true_concept:
            s.n_correct += 1
            s._bump(s.class_correct, klass)
        elif pred_concept == "unmapped":
            s._bump(s.class_abstain, klass)
        else:
            s._bump(s.class_mislabel, klass)

        # confusion (per concept label)
        if pred_concept == true_concept:
            s._bump(s.tp, true_concept)
        else:
            s._bump(s.fp, pred_concept)
            s._bump(s.fn, true_concept)

        if pred_concept == "revenue":
            pred_revenue.append(value)
        elif pred_concept == "cost_of_goods_sold":
            pred_cogs.append(value)

    # metric reconstruction from the predicted value-sets
    s.gp_truth = fixture.gross_profit
    s.gp_pred = sum(fixture.totals[v] for v in pred_revenue) - sum(
        fixture.totals[v] for v in pred_cogs
    )
    return s


@dataclass
class Pooled:
    leg: str
    accuracy: float
    class_accuracy: dict[str, float]
    macro_precision: float
    macro_recall: float
    gp_rel_error: float  # mean |pred-truth|/|truth| over seeds
    # per class: (correct, abstain, mislabel) as fractions of that class's values
    class_breakdown: dict[str, tuple[float, float, float]] = field(default_factory=dict)


def pool(leg: str, scores: list[LegScore]) -> Pooled:
    n_values = sum(s.n_values for s in scores) or 1
    accuracy = sum(s.n_correct for s in scores) / n_values

    classes = {k for s in scores for k in s.class_total}
    class_acc = {}
    breakdown = {}
    for k in sorted(classes):
        tot = sum(s.class_total.get(k, 0) for s in scores) or 1
        cor = sum(s.class_correct.get(k, 0) for s in scores)
        abst = sum(s.class_abstain.get(k, 0) for s in scores)
        mis = sum(s.class_mislabel.get(k, 0) for s in scores)
        class_acc[k] = cor / tot
        breakdown[k] = (cor / tot, abst / tot, mis / tot)

    concepts = {c for s in scores for c in (set(s.tp) | set(s.fp) | set(s.fn))}
    precs, recs = [], []
    for c in concepts:
        tp = sum(s.tp.get(c, 0) for s in scores)
        fp = sum(s.fp.get(c, 0) for s in scores)
        fn = sum(s.fn.get(c, 0) for s in scores)
        if tp + fp:
            precs.append(tp / (tp + fp))
        if tp + fn:
            recs.append(tp / (tp + fn))
    macro_p = sum(precs) / len(precs) if precs else 0.0
    macro_r = sum(recs) / len(recs) if recs else 0.0

    rel_errs = [
        abs(s.gp_pred - s.gp_truth) / abs(s.gp_truth)
        for s in scores
        if s.gp_truth
    ]
    gp_err = sum(rel_errs) / len(rel_errs) if rel_errs else 0.0

    return Pooled(
        leg=leg,
        accuracy=accuracy,
        class_accuracy=class_acc,
        macro_precision=macro_p,
        macro_recall=macro_r,
        gp_rel_error=gp_err,
        class_breakdown=breakdown,
    )
