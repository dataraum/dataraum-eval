"""Cardinality bucketing as the identity pre-filter (Philipp's design).

A bijection requires equal cardinality, so bucket columns by exact distinct
count; only same-bucket pairs can be aliases. Test on clean-flat: does the
account identity set cluster? Do the declared fold attributes land together?
Dirty aliases (unequal-by-k cardinality) are expected to split buckets — that's
the known tolerance gap, flagged not fixed.

No LLM. Uses metadata_truth for the identity set.
"""
import polars as pl, yaml
from collections import defaultdict
from pathlib import Path

base = Path("/Users/philipp/Code/dataraum/dataraum-eval/data/clean-flat")
truth = yaml.safe_load((base / "metadata_truth.yaml").read_text())
fold = truth["folded_dimensions"][0]
identity_cols = set([fold["fold_key"]] + fold["attributes"])  # the account dimension

for table in ("general_ledger.csv", "trial_balance.csv"):
    df = pl.read_csv(base / table, infer_schema_length=0)
    n = df.height
    card = {c: df[c].drop_nulls().n_unique() for c in df.columns}
    buckets = defaultdict(list)
    for c, d in card.items():
        buckets[d].append(c)

    print(f"=== {table} ({n:,} rows) — cardinality buckets ===")
    # pairwise cost: flat O(n^2) vs sum of within-bucket
    ncol = len(df.columns)
    flat = ncol * (ncol - 1) // 2
    bucketed = sum(len(v) * (len(v) - 1) // 2 for v in buckets.values())
    print(f"  columns={ncol}  flat-pairs={flat}  within-bucket-pairs={bucketed}  "
          f"(g3 work cut {100*(1-bucketed/flat):.0f}%)")
    for d in sorted(buckets, reverse=True):
        cols = buckets[d]
        if len(cols) < 2 and not (set(cols) & identity_cols):
            continue
        tag = []
        for c in cols:
            tag.append(f"{c}{'*' if c in identity_cols else ''}")
        multi = "  <- multi-col bucket (alias candidates)" if len(cols) > 1 else ""
        print(f"    distinct={d:>6}: {', '.join(tag)}{multi}")

    # where did the identity set land?
    print("  identity set (account dimension, * above):")
    idbuck = defaultdict(list)
    for c in identity_cols:
        if c in card:
            idbuck[card[c]].append(c)
    for d, cols in sorted(idbuck.items()):
        note = "" if len(cols) > 1 else "  (alone in its bucket — not a bijection candidate here)"
        print(f"    distinct={d}: {cols}{note}")
    print()
