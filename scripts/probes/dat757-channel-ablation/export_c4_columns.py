"""C4 TFM leg — stage 1: export the pre-registered 22-column pool for the tfm env.

The tfm/ project is an isolated uv env (torch/tabicl, no polars/duckdb), so the
eval env exports the pool as JSON: {column_key: {"name": <raw name for the names
baseline>, "concept": <pre-registered concept label>, "values": [<=2048 sampled
values as strings, nulls as "␀">]}}.

Same-concept pairs (12, pre-registered): the 6 cross-country REGION partition
pairs, nationality<->country, the 4 hm code<->name pairs, date<->race__date.
Every other pair in the pool is a different-concept negative.

Run:  uv run python scripts/probes/dat757-channel-ablation/export_c4_columns.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parents[0] / ".." / "dat757-relbench"))
from probe_fold_grade import SPECS, build_obt  # noqa: E402

OUT = Path("tfm/dat757/c4_columns.json")
N_SAMPLE = 2048
NULL = "␀"


def sample(obt: pl.DataFrame, col: str, flt=None) -> list[str]:
    s = obt.filter(flt) if flt is not None else obt
    s = s.get_column(col).cast(pl.Utf8).fill_null(NULL)
    if len(s) > N_SAMPLE:
        s = s.sample(N_SAMPLE, seed=757)
    return s.to_list()


def main() -> None:
    pool: dict[str, dict] = {}

    salt, _ = build_obt(Path("corpora/relbench/rel-salt"), SPECS["rel-salt"])
    top4 = (salt.get_column("soldto_addr__COUNTRY").drop_nulls().value_counts()
            .sort("count", descending=True)["soldto_addr__COUNTRY"][:4].to_list())
    for i, ctry in enumerate(top4, 1):
        pool[f"region_v{i}"] = {
            "name": "region", "concept": "geo-region",
            "values": sample(salt, "soldto_addr__REGION",
                             pl.col("soldto_addr__COUNTRY") == ctry),
        }
    pool["salesoffice"] = {"name": "SALESOFFICE", "concept": "org-office",
                           "values": sample(salt, "doc__SALESOFFICE")}
    pool["salesgroup"] = {"name": "SALESGROUP", "concept": "org-group",
                          "values": sample(salt, "doc__SALESGROUP")}

    f1, _ = build_obt(Path("corpora/relbench/rel-f1"), SPECS["rel-f1"])
    for key, col, concept in (
        ("nationality", "driver__nationality", "geo-country"),
        ("country", "circuit__country", "geo-country"),
        ("number", "number", "car-number"),
        ("grid", "grid", "grid-slot"),
        ("date", "date", "race-date"),
        ("race_date", "race__date", "race-date"),
    ):
        pool[key] = {"name": col.split("__")[-1], "concept": concept,
                     "values": sample(f1, col)}

    hm, _ = build_obt(Path("corpora/relbench/rel-hm"), SPECS["rel-hm"])
    for attr in ("colour_group", "section", "garment_group", "index"):
        for suffix, kind in (("code", "code"), ("name", "name")):
            col = {
                ("colour_group", "code"): "article__colour_group_code",
                ("colour_group", "name"): "article__colour_group_name",
                ("section", "code"): "article__section_no",
                ("section", "name"): "article__section_name",
                ("garment_group", "code"): "article__garment_group_no",
                ("garment_group", "name"): "article__garment_group_name",
                ("index", "code"): "article__index_code",
                ("index", "name"): "article__index_name",
            }[(attr, suffix)]
            pool[f"{attr}_{kind}"] = {"name": col.removeprefix("article__"),
                                      "concept": attr, "values": sample(hm, col)}
    pool["fn"] = {"name": "FN", "concept": "flag-fn", "values": sample(hm, "customer__FN")}
    pool["active"] = {"name": "Active", "concept": "flag-active",
                      "values": sample(hm, "customer__Active")}

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(pool, ensure_ascii=False))
    print(f"exported {len(pool)} columns -> {OUT}")
    # geo-region partitions share a concept; nationality/country share geo-country;
    # code/name pairs share their attribute concept; date/race_date share race-date
    concepts: dict[str, list[str]] = {}
    for k, v in pool.items():
        concepts.setdefault(v["concept"], []).append(k)
    pos = sum(len(v) * (len(v) - 1) // 2 for v in concepts.values())
    print(f"same-concept pairs: {pos} (expect 12)")


if __name__ == "__main__":
    main()
