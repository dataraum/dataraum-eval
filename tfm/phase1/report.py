"""DAT-743 Phase 1: aggregate the probe JSONLs into findings tables.

    uv run python report.py [p1|p2|p3|p4|p6|tiers|all]

Read-only over tfm/output/phase1/*.jsonl; keeps the last row per
(engine, config) key so re-runs supersede earlier rows.
"""

from __future__ import annotations

import json
import sys

import pandas as pd

import results as rs


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    key = df["config"].map(lambda c: json.dumps(c, sort_keys=True)) + "|" + df["engine"]
    return df[~key.duplicated(keep="last")]


def _rows(probe: str, full_only: bool = True) -> pd.DataFrame:
    df = _dedupe(rs.load(probe))
    if df.empty:
        return df
    if full_only:
        df = df[~df["config"].map(lambda c: c.get("smoke", False))]
    return df.reset_index(drop=True)


def p1() -> None:
    df = _rows("p1_forecast")
    df = df[df["metrics"].map(lambda m: "error" not in m)]
    flat = pd.json_normalize(df["metrics"])  # type: ignore[arg-type]
    flat["engine"] = df["engine"].to_numpy()
    flat["latency_s"] = df["latency_s"].to_numpy()
    agg = flat.groupby("engine").agg(
        wape=("wape", "mean"), crps=("crps", "mean"),
        cover80=("cover80", "mean"), cover95=("cover95", "mean"),
        wape_h1=("wape_h1", "mean"), wape_h3=("wape_h3", "mean"),
        latency_s=("latency_s", "mean"), n_origins=("wape", "size"),
    ).sort_values("crps")
    print("== P1 forecast (mean over rolling origins; 135 series, h=1-3)")
    print(agg.round(3).to_string())


def p2() -> None:
    df = _rows("p2_importance")
    rows = []
    for _, r in df.iterrows():
        m = r["metrics"]
        rows.append({
            "target": r["config"]["target"], "engine": r["engine"],
            "spearman": m.get("spearman"), "kendall": m.get("kendall"),
            "top_k_exact": m.get("top_k_exact"), "error": m.get("error", ""),
            "latency_s": r["latency_s"],
        })
    print("== P2 structure recovery (rank agreement vs DGP formula)")
    print(pd.DataFrame(rows).round(3).to_string(index=False))


def p3() -> None:
    df = _rows("p3_anomaly")
    rows = []
    for _, r in df.iterrows():
        m, c = r["metrics"], r["config"]
        base = {"corpus": c["corpus"].removeprefix("p3-"), "table": c["table"],
                "shaping": c["shaping"], "engine": r["engine"]}
        if "error" in m:
            rows.append(base | {"type": "ERROR", "note": m["error"][:60]})
            continue
        for kind, v in m.items():
            if not isinstance(v, dict) or "auroc" not in v:
                continue
            rows.append(base | {"type": kind, "auroc": v["auroc"], "ap": v["ap"],
                                "p@budget": v["p_at_budget"], "n_pos": v["n_pos"]})
    out = pd.DataFrame(rows)
    if out.empty:
        print("== P3: no rows yet")
        return
    print("== P3 anomaly AUROC by (type, corpus, engine) — 'all' = any injection")
    pivot = out[out["type"] == "all"].pivot_table(
        index=["table", "shaping"], columns=["engine", "corpus"], values="auroc"
    )
    print(pivot.round(3).to_string())
    print("\n-- per injection type (auroc, medium-s42, bare)")
    sel = out[(out["corpus"] == "medium-s42") & (out["shaping"] == "bare")
              & (out["type"] != "all")]
    if not sel.empty:
        print(sel.pivot_table(index=["table", "type"], columns="engine",
                              values="auroc").round(3).to_string())


def p4() -> None:
    df = _rows("p4_conditioning")
    rows = []
    for _, r in df.iterrows():
        m = r["metrics"]
        rows.append({
            "engine": r["engine"], "feature_set": r["config"]["feature_set"],
            "wape": m.get("wape"), "lift_vs_base": m.get("lift_vs_base"),
            "error": m.get("error", ""), "latency_s": r["latency_s"],
        })
    print("== P4 conditioning (lift vs base; calendar=real signal, fx=negative control)")
    print(pd.DataFrame(rows).round(4).to_string(index=False))


def p6() -> None:
    df = _rows("p6_impute")
    rows = []
    for _, r in df.iterrows():
        m = r["metrics"]
        rows.append({
            "method": r["engine"], "mask_rate": r["config"]["mask_rate"],
            "nrmse_num": m.get("nrmse_numeric_mean"),
            "acc_cat": m.get("acc_categorical_mean"),
            "error": m.get("error", ""), "latency_s": r["latency_s"],
        })
    print("== P6 imputation (masked-cell recovery)")
    print(pd.DataFrame(rows).round(3).to_string(index=False))


def tiers() -> None:
    df = _rows("tiers")
    rows = []
    for _, r in df.iterrows():
        m = r["metrics"]
        rows.append({
            "task": r["config"]["task"], "context": r["config"]["context_rows"],
            "engine": r["engine"], "acc": m.get("acc"), "r2": m.get("r2"),
            "error": m.get("error", ""), "latency_s": r["latency_s"],
        })
    print("== data efficiency tiers")
    print(pd.DataFrame(rows).round(3).to_string(index=False))


SECTIONS = {"p1": p1, "p2": p2, "p3": p3, "p4": p4, "p6": p6, "tiers": tiers}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name, fn in SECTIONS.items():
        if which in (name, "all"):
            fn()
            print()
