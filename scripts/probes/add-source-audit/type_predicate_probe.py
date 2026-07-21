"""Does a parquet column type survive the engine's type predicates?

The engine decides "is this numeric / is this temporal" in five places. Two are
written robustly (case-folded, precision-stripped, containment); three compare
DuckDB's verbatim type string against a hardcoded 4-item list. The strongly-typed
loader stores DuckDB's verbatim ``DESCRIBE`` name in ``resolved_type``, so the
question is empirical: which real parquet types does each predicate accept?

rel-f1 only carries BIGINT / DOUBLE / VARCHAR / TIMESTAMP_NS, so it exercises one
narrow corner. This writes a parquet spanning the ordinary type space and reports
what each predicate would decide — milliseconds, no pipeline.

    uv run python scripts/probes/add-source-audit/type_predicate_probe.py
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# The three brittle copies (statistical_quality_phase.py:78, profiler.py:102,
# quality.py:433, derived_columns.py:381) — verbatim.
BRITTLE_NUMERIC = ["INTEGER", "BIGINT", "DOUBLE", "DECIMAL"]
# The robust copy (analysis/lineage/processor.py:_is_numeric) — verbatim.
ROBUST_NUMERIC = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL"}
# temporal_phase.py:64 — verbatim.
BRITTLE_TEMPORAL = ["DATE", "TIMESTAMP", "TIMESTAMPTZ"]
# temporal_entropy.py:37 — substring containment.
ROBUST_TEMPORAL = frozenset({"DATE", "TIME", "TIMESTAMP", "DATETIME", "INTERVAL"})

SELECT = """
SELECT
    42::TINYINT              AS c_tinyint,
    42::SMALLINT             AS c_smallint,
    42::INTEGER              AS c_integer,
    42::BIGINT               AS c_bigint,
    42::HUGEINT              AS c_hugeint,
    42::UBIGINT              AS c_ubigint,
    42.5::FLOAT              AS c_float,
    42.5::DOUBLE             AS c_double,
    42.50::DECIMAL(18,2)     AS c_decimal_18_2,
    DATE '2026-01-01'        AS c_date,
    TIMESTAMP '2026-01-01'   AS c_timestamp,
    TIMESTAMPTZ '2026-01-01' AS c_timestamptz,
    'x'                      AS c_varchar
"""


def _is_numeric_robust(t: str) -> bool:
    return t.split("(")[0].strip().upper() in ROBUST_NUMERIC


def main() -> None:
    out = Path("/private/tmp/type_predicate_probe.parquet")
    conn = duckdb.connect()
    conn.execute(f"COPY ({SELECT}) TO '{out}' (FORMAT PARQUET)")
    # Exactly what sources/parquet/loader.py stores in raw_type → resolved_type.
    described = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{out}')").fetchall()

    print(f"{'column':<18} {'resolved_type':<16} {'num(4-list)':<12} {'num(robust)':<12} "
          f"{'temporal(list)':<15} temporal(substr)")
    gaps: list[str] = []
    for name, dtype, *_ in described:
        t = str(dtype)
        nb, nr = t in BRITTLE_NUMERIC, _is_numeric_robust(t)
        tb = t in BRITTLE_TEMPORAL
        tr = any(d in t.upper() for d in ROBUST_TEMPORAL)
        print(f"{name:<18} {t:<16} {nb!s:<12} {nr!s:<12} {tb!s:<15} {tr}")
        if nb != nr or tb != tr:
            gaps.append(f"{t}: numeric {nb}->{nr}, temporal {tb}->{tr}")

    print(f"\n{len(gaps)} type(s) where the brittle and robust predicates DISAGREE:")
    for g in gaps:
        print(f"  {g}")
    # The TIMESTAMP_NS case only appears via a nanosecond parquet, which pandas
    # (and therefore RelBench) writes by default.
    conn.execute(
        f"COPY (SELECT TIMESTAMP_NS '2026-01-01' AS c_ts_ns) TO '{out}' (FORMAT PARQUET)"
    )
    ns = str(conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{out}')").fetchall()[0][1])
    print(f"\nnanosecond parquet resolved_type = {ns!r}: "
          f"temporal(list)={ns in BRITTLE_TEMPORAL}, "
          f"temporal(substr)={any(d in ns.upper() for d in ROBUST_TEMPORAL)}")


if __name__ == "__main__":
    main()
