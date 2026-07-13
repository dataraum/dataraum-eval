"""DAT-743 P3: density-based anomaly detection vs entropy_map labels.

The payoff probe: can a generic joint-density model flag injected defects?
Unsupervised setting matching the detector suite's reality — fit on the
contaminated table itself, score every row, no labels at fit time.

Grid: corpora (severity ladder low/medium/high seed 42, medium seed 43 as
replicate, clean s42 as reference) x tables x shaping {bare, enriched} x
scorers {tabicl2, tabpfn3, isolation_forest}. Rows subsampled to N_MAX for
tractability — same subsample for every scorer (seeded), labels ride along.

Metrics per (table, injection_type): AUROC / AP / precision@budget of that
type's rows vs the table's uninjected rows (other types excluded from the
negatives). "all" = any-injection vs clean rows. Types whose labels cover
(almost) the whole table have no within-table negative class -> recorded
as coverage, not scored. Clean corpora record score-distribution summaries
(no positives to rank).

Usage: uv run python p3_anomaly.py [--smoke] [--scorers tabicl2,...]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import baselines as bl
import data
import engines as eng
import ground_truth as gt
import metrics as mx
import results as rs

PROBE = "p3_anomaly"
N_MAX = 4000
SEED = 42

CORPORA = ("p3-low-s42", "p3-medium-s42", "p3-high-s42", "p3-medium-s43", "p3-clean-s42")
ENRICHABLE = ("payments", "journal_lines", "trial_balance")


def scorers(names: list[str]) -> dict:
    return {
        "tabicl2": lambda X: eng.ENGINES["tabicl2"].anomaly_scores(X),
        "tabpfn3": lambda X: eng.ENGINES["tabpfn3"].anomaly_scores(X),
        "isolation_forest": bl.isolation_forest_scores,
    } | {}


def evaluate(labels: pd.DataFrame, scores: np.ndarray) -> dict:
    """Per-type + overall ranking metrics; degenerate types recorded."""
    out: dict = {}
    clean_mask = labels["label"].to_numpy() == 0
    out["all"] = mx.anomaly_metrics(labels["label"].to_numpy(), scores)
    for kind in [c for c in labels.columns if c != "label"]:
        pos = labels[kind].to_numpy() == 1
        mask = pos | clean_mask
        if pos.all() or not clean_mask.any():
            out[kind] = {"n_pos": int(pos.sum()), "degenerate": "no negative class"}
            continue
        out[kind] = mx.anomaly_metrics(pos[mask].astype(int), scores[mask])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--scorers", default="isolation_forest,tabicl2,tabpfn3")
    ap.add_argument("--corpora", default=",".join(CORPORA))
    args = ap.parse_args()

    corpora = args.corpora.split(",")
    tables = data.P3_TABLES
    n_max = N_MAX
    if args.smoke:
        corpora = ["p3-medium-s42"]
        tables = ("trial_balance", "invoices")
        n_max = 500

    fns = scorers(args.scorers.split(","))
    for corpus in corpora:
        for table in tables:
            shapings = ("bare", "enriched") if table in ENRICHABLE else ("bare",)
            for shaping in shapings:
                X = data.p3_table(corpus, table, enriched=shaping == "enriched")
                labels = gt.row_labels(data.TFM_DATA / corpus, table)
                if len(X) > n_max:
                    idx = X.sample(n=n_max, random_state=SEED).index
                    X, labels = X.loc[idx].reset_index(drop=True), labels.loc[idx].reset_index(drop=True)
                for name in args.scorers.split(","):
                    config = {"corpus": corpus, "table": table, "shaping": shaping,
                              "n": len(X), "smoke": args.smoke}
                    try:
                        with rs.timed() as t:
                            scores = np.asarray(fns[name](X), dtype=float)
                        if "clean" in corpus:
                            metrics = {"score_mean": float(np.nanmean(scores)),
                                       "score_p95": float(np.nanquantile(scores, 0.95)),
                                       "score_p99": float(np.nanquantile(scores, 0.99))}
                        else:
                            metrics = evaluate(labels, scores)
                    except Exception as exc:  # a failing scorer is a finding
                        rs.record(PROBE, name, config, {"error": f"{type(exc).__name__}: {exc}"})
                        continue
                    rs.record(PROBE, name, config, metrics, latency_s=t["s"])


if __name__ == "__main__":
    main()
