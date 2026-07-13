"""Shape smoke check for phase1/data.py builders (DAT-743)."""

import data
import ground_truth as gt

series = data.monthly_series()
n_items = series["item_id"].nunique()
print(f"P1 series: {len(series)} rows, {n_items} items, "
      f"{series.groupby('item_id').size().min()}-{series.groupby('item_id').size().max()} months/item")
ctx, fut = data.split_origin(series, 36)
print(f"  origin=36: context {len(ctx)}, future {len(fut)} (expect items*3={n_items * 3})")

for table in data.P3_TABLES:
    for enriched in (False, True):
        df = data.p3_table("p3-medium-s42", table, enriched)
        labels = gt.row_labels(data.TFM_DATA / "p3-medium-s42", table)
        tag = "enriched" if enriched else "bare"
        assert len(df) == len(labels), f"{table} {tag}: {len(df)} != {len(labels)}"
        print(f"P3 {table:18s} {tag:8s}: {df.shape}, positives={labels['label'].sum()}")

X, y = data.p2_net_amount()
print(f"P2a net_amount: X{X.shape}, y std={y.std():.0f}")
X, y = data.p2_tb_balance(side="debit")
print(f"P2b tb debit:   X{X.shape}, corr(sum_debit, y)={X['sum_debit'].corr(y):.4f}")

p4 = data.p4_supervised()
print(f"P4 frame: {p4.shape}, fx cols={[c for c in p4.columns if c.startswith('fx_')]}")
q4 = p4[p4['month'].isin([10, 11, 12])]['target'].abs().mean()
rest = p4[~p4['month'].isin([10, 11, 12])]['target'].abs().mean()
print(f"  |target| Q4 vs rest: {q4:.0f} vs {rest:.0f} (boost visible: {q4 > rest})")

Xr, yr = data.supervised_regression()
Xc, yc = data.supervised_classification()
print(f"tiers: regression X{Xr.shape}, classification X{Xc.shape} ({yc.nunique()} classes)")
print(f"P6 table: {data.p6_table().shape}")
