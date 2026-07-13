"""Verify the enriched-TB gap features isolate injected rows (DAT-743 P3)."""

import data
import ground_truth as gt

for corpus in ("p3-high-s42", "p3-medium-s42"):
    X = data.p3_table(corpus, "trial_balance", enriched=True)
    labels = gt.row_labels(data.TFM_DATA / corpus, "trial_balance")
    gap = (X["debit_gap"].abs().fillna(0) + X["credit_gap"].abs().fillna(0))
    pos, neg = gap[labels["label"] == 1], gap[labels["label"] == 0]
    print(f"{corpus}: n_pos={len(pos)} |gap| pos median={pos.median():.2f} "
          f"p10={pos.quantile(0.1):.2f} | neg median={neg.median():.2f} "
          f"p99={neg.quantile(0.99):.2f} | separation={(pos > neg.quantile(0.99)).mean():.2f}")
