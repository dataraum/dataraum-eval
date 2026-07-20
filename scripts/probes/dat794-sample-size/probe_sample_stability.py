"""DAT-794 — sample-size stability probe for Layer-A relationship detection.

CLAIM UNDER TEST (to refute)
    Layer-A FK candidate detection is nondeterministic because of exactly two
    unseeded sampling sites in the engine —

      (1) finder.py:124   uniqueness ratio over `USING SAMPLE {p}% (bernoulli)`
                          (default p=10), served to the semantic LLM prompt as
                          `[uniq: L=x.xx R=x.xx]` → prompt churn;
      (2) joins.py:410/417 `USING SAMPLE reservoir({m} ROWS)` over DISTINCT
                          values on the SAMPLED path (10K ≤ max_distinct < 1M),
                          feeding the hard gate score≥0.3 AND confidence≥0.5

    — and there exists a policy "full scan below N distinct, seeded sample at
    rate M above" under which all true-FK pairs are detected 50/50.

    Sharp sub-prediction (sampling theory, computed before running):
    invoices.entry_id → journal_entries.entry_id (3,000 ⊂ 11,754 distinct) has
    true Jaccard 3000/11754 ≈ 0.255 < 0.3, so it survives Layer A ONLY through
    the containment≥0.95 cliff; the containment estimate's sampling SE at the
    engine's m1=1000, m2=1175 is ~10% ⇒ the pair should DROP OUT in a
    non-trivial fraction of unseeded runs. If the observed detection rate is
    ~100%, the claim is refuted and the instability lives elsewhere.

THE ATTACK
    (a) the smallest table (chart_of_accounts, 60 rows), where a 10% bernoulli
        sample starves; (b) the only pairs on the reservoir path — the two
        involving journal_entries.entry_id (11,754 distinct > the 10K exact
        threshold) — where subset FKs sit on the containment cliff; (c) DuckDB
        seeded-sampling semantics under multithreading (percentage sampling is
        documented as thread-order sensitive — a seed alone may NOT be enough).

LEGS
    1. path classification — every true-FK pair → EXACT / SAMPLED / MINHASH +
       the _should_compare_columns filters (exact distinct counts, no sampling)
    2. reservoir stability — engine CTE verbatim, 50 reps × rate grid, per
       SAMPLED pair: detection rate, score/confidence spread, containment flips
    3. bernoulli uniqueness stability — engine SQL verbatim, 50 reps ×
       p ∈ {1,5,10,25,50,100} per FK column: ratio spread, prompt-visible churn
    4. determinism of seeded variants — same seed 20×, threads ∈ {1, 4}
    5. cost of exactness — exact vs sampled Jaccard CTE and full vs sampled
       uniqueness at 10K / 100K / 1M distinct → where sampling actually pays

Everything is DuckDB over the generated corpora on disk: milliseconds per
query, no docker, no pipeline, no LLM.
"""

from __future__ import annotations

import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import yaml

REPO = Path(__file__).resolve().parents[3]
CORPORA = ["clean", "detection-v1"]
REPS = 50
SEED_REPS = 20

# Engine constants, mirrored from joins.py / finder.py (values asserted against
# source in the report header so drift is loud).
SMALL_CARDINALITY_THRESHOLD = 10_000
LARGE_CARDINALITY_THRESHOLD = 1_000_000
MIN_SAMPLE_SIZE = 1000
DEFAULT_SAMPLE_RATE = 0.1
MIN_SCORE = 0.3  # detector.py min_confidence -> joins.py min_score
MIN_CONFIDENCE = 0.5  # joins.py MIN_CONFIDENCE_THRESHOLD
UNIQUENESS_SAMPLE_PERCENT = 10.0  # finder.py sample_percent default


@dataclass
class Pair:
    """One ground-truth FK: from_table.from_col -> to_table.to_col."""

    from_table: str
    from_col: str
    to_table: str
    to_col: str

    def __str__(self) -> str:
        return f"{self.from_table}.{self.from_col} -> {self.to_table}.{self.to_col}"


def load_corpus(corpus: str) -> tuple[duckdb.DuckDBPyConnection, list[Pair]] | None:
    data_dir = REPO / "data" / corpus
    truth_path = data_dir / "metadata_truth.yaml"
    if not truth_path.exists():
        print(f"  !! {corpus}: no metadata_truth.yaml — skipped")
        return None
    truth = yaml.safe_load(truth_path.read_text())
    pairs = [
        Pair(*r["from"].split("."), *r["to"].split("."))
        for r in truth["relationships"]
    ]
    conn = duckdb.connect()
    for csv in sorted(data_dir.glob("*.csv")):
        conn.execute(
            f'CREATE TABLE "{csv.stem}" AS SELECT * FROM read_csv_auto(?)', [str(csv)]
        )
    return conn, pairs


def distinct_stats(conn: duckdb.DuckDBPyConnection, table: str, col: str) -> tuple[int, int]:
    """Exact (distinct_count, non_null_count) — mirrors _precompute_column_stats."""
    row = conn.execute(
        f'SELECT COUNT(DISTINCT "{col}"), COUNT(*) FILTER (WHERE "{col}" IS NOT NULL) '
        f'FROM "{table}"'
    ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def algorithm_for(max_distinct: int) -> str:
    if max_distinct < SMALL_CARDINALITY_THRESHOLD:
        return "EXACT"
    if max_distinct < LARGE_CARDINALITY_THRESHOLD:
        return "SAMPLED"
    return "MINHASH"


# ---------------------------------------------------------------- leg 2 SQL --


def reservoir_cte(
    t1: str, c1: str, t2: str, c2: str, m1: int, m2: int, seed: int | None = None
) -> str:
    """The joins.py _compute_sampled_jaccard CTE, verbatim shape (+ optional seed)."""
    rep = f" REPEATABLE ({seed})" if seed is not None else ""
    return f"""
        WITH
        sampled1 AS (
            SELECT v FROM (
                SELECT DISTINCT "{c1}" AS v FROM "{t1}" WHERE "{c1}" IS NOT NULL
            ) USING SAMPLE reservoir({m1} ROWS){rep}
        ),
        sampled2 AS (
            SELECT v FROM (
                SELECT DISTINCT "{c2}" AS v FROM "{t2}" WHERE "{c2}" IS NOT NULL
            ) USING SAMPLE reservoir({m2} ROWS){rep}
        ),
        actual_counts AS (
            SELECT
                (SELECT COUNT(*) FROM sampled1) AS m1_actual,
                (SELECT COUNT(*) FROM sampled2) AS m2_actual,
                (SELECT COUNT(*) FROM sampled1 WHERE v IN (SELECT v FROM sampled2)) AS x
        )
        SELECT m1_actual, m2_actual, x FROM actual_counts
    """


def score_sampled(
    n1: int, n2: int, m1_actual: int, m2_actual: int, x: int
) -> tuple[float, float, float]:
    """(score, confidence, containment) — arithmetic mirrored from joins.py."""
    if m1_actual == 0 or m2_actual == 0:
        return 0.0, 0.0, 0.0
    intersection = x * n1 * n2 / (m1_actual * m2_actual)
    union = n1 + n2 - intersection
    jaccard = intersection / union if union > 0 else 0.0
    containment = 0.0
    if min(n1, n2) > 10:
        c1 = intersection / n1 if n1 > 0 else 0.0
        c2 = intersection / n2 if n2 > 0 else 0.0
        containment = 1.0 if (c1 >= 0.95 or c2 >= 0.95) else 0.0
    score = max(0.0, min(1.0, max(jaccard, containment)))
    confidence = max(0.0, min(1.0, 1.0 - 1.0 / math.sqrt(x))) if x > 0 else 0.1
    return score, confidence, containment


def exact_jaccard_sql(t1: str, c1: str, t2: str, c2: str) -> str:
    """The joins.py _compute_exact_jaccard intersection query, verbatim shape."""
    return f"""
        WITH
        vals1 AS (SELECT DISTINCT "{c1}" AS v FROM "{t1}" WHERE "{c1}" IS NOT NULL),
        vals2 AS (SELECT DISTINCT "{c2}" AS v FROM "{t2}" WHERE "{c2}" IS NOT NULL)
        SELECT COUNT(*) FROM vals1 WHERE v IN (SELECT v FROM vals2)
    """


# ---------------------------------------------------------------- leg 3 SQL --


def uniqueness_sql(table: str, col: str, percent: float, seed: int | None = None) -> str:
    """The finder.py _uniqueness_ratio SQL, verbatim shape (+ optional seed)."""
    method = f"bernoulli, {seed}" if seed is not None else "bernoulli"
    return (
        f'SELECT COUNT(DISTINCT "{col}")::DOUBLE / NULLIF(COUNT(*), 0) '
        f'FROM (SELECT "{col}" FROM "{table}" USING SAMPLE {percent}% ({method}))'
    )


def uniqueness_once(conn: duckdb.DuckDBPyConnection, sql: str) -> float:
    row = conn.execute(sql).fetchone()
    return round(row[0], 4) if row and row[0] is not None else 0.0


# -------------------------------------------------------------------- legs --


def leg1_paths(
    conn: duckdb.DuckDBPyConnection, pairs: list[Pair]
) -> dict[str, tuple[Pair, int, int]]:
    """Classify every true-FK pair; return the SAMPLED-path subset."""
    print("\n  LEG 1 — algorithm path per true-FK pair (exact distinct counts)")
    print(f"  {'pair':<58} {'n1':>6} {'n2':>6} {'ratio':>6}  path    filters")
    sampled: dict[str, tuple[Pair, int, int]] = {}
    for p in pairs:
        n1, t1 = distinct_stats(conn, p.from_table, p.from_col)
        n2, t2 = distinct_stats(conn, p.to_table, p.to_col)
        ratio = max(n1, n2) / max(min(n1, n2), 1)
        algo = algorithm_for(max(n1, n2))
        flags = []
        if n1 <= 1 or n2 <= 1:
            flags.append("CONSTANT-SKIP")
        if ratio > 100.0:
            flags.append("RATIO-SKIP(>100)")
        print(
            f"  {str(p):<58} {n1:>6} {n2:>6} {ratio:>6.1f}  {algo:<7} "
            f"{','.join(flags) or 'pass'}"
        )
        if algo == "SAMPLED" and not flags:
            sampled[str(p)] = (p, n1, n2)
    return sampled


def leg2_reservoir(
    conn: duckdb.DuckDBPyConnection, sampled: dict[str, tuple[Pair, int, int]]
) -> list[str]:
    """Unseeded reservoir stability at the engine's parameters + a rate grid."""
    print(f"\n  LEG 2 — reservoir Jaccard stability ({REPS} unseeded reps per cell)")
    findings: list[str] = []
    for key, (p, n1, n2) in sampled.items():
        # exact truth for reference
        row = conn.execute(exact_jaccard_sql(p.from_table, p.from_col, p.to_table, p.to_col)).fetchone()
        assert row is not None
        inter_true = int(row[0])
        j_true = inter_true / (n1 + n2 - inter_true)
        cont_true = max(inter_true / n1, inter_true / n2)
        print(f"\n  {key}")
        print(f"    exact: jaccard={j_true:.3f} containment={cont_true:.3f} "
              f"(gate needs score>={MIN_SCORE} & conf>={MIN_CONFIDENCE})")
        print(f"    {'rate':>5} {'m1':>5} {'m2':>5} | {'detect':>7} {'score min/med/max':>20} "
              f"{'conf med':>8} {'cont=1':>6}")
        for rate in (DEFAULT_SAMPLE_RATE, 0.25, 0.5):
            m1 = min(max(MIN_SAMPLE_SIZE, int(n1 * rate)), n1)
            m2 = min(max(MIN_SAMPLE_SIZE, int(n2 * rate)), n2)
            sql = reservoir_cte(p.from_table, p.from_col, p.to_table, p.to_col, m1, m2)
            scores, confs, conts, detects = [], [], [], 0
            for _ in range(REPS):
                r = conn.execute(sql).fetchone()
                assert r is not None
                s, c, cont = score_sampled(n1, n2, int(r[0]), int(r[1]), int(r[2]))
                scores.append(s)
                confs.append(c)
                conts.append(cont)
                detects += s >= MIN_SCORE and c >= MIN_CONFIDENCE
            tag = "" if detects == REPS else "   << FLAPS"
            marker = " (engine default)" if rate == DEFAULT_SAMPLE_RATE else ""
            print(
                f"    {rate:>5.2f} {m1:>5} {m2:>5} | {detects:>3}/{REPS:<3} "
                f"{min(scores):>6.3f}/{statistics.median(scores):.3f}/{max(scores):.3f} "
                f"{statistics.median(confs):>8.3f} {sum(conts)/REPS:>6.2f}{tag}{marker}"
            )
            if detects < REPS:
                findings.append(
                    f"{key}: rate={rate:.2f} detects {detects}/{REPS} "
                    f"(score min {min(scores):.3f} vs gate {MIN_SCORE})"
                )
    return findings


def leg3_uniqueness(conn: duckdb.DuckDBPyConnection, pairs: list[Pair]) -> list[str]:
    """Bernoulli uniqueness-ratio spread per FK column across sample percents."""
    print(f"\n  LEG 3 — bernoulli uniqueness stability ({REPS} unseeded reps per cell)")
    cols = sorted({(p.from_table, p.from_col) for p in pairs} | {(p.to_table, p.to_col) for p in pairs})
    findings: list[str] = []
    print(f"  {'column':<38} {'rows':>6} | per p%: min..max ratio (distinct 2dp renderings)")
    for table, col in cols:
        nrows = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        full = uniqueness_once(conn, uniqueness_sql(table, col, 100.0))
        cells = []
        worst_churn = 0
        for pct in (1.0, 5.0, 10.0, 25.0, 50.0):
            vals = [uniqueness_once(conn, uniqueness_sql(table, col, pct)) for _ in range(REPS)]
            churn = len({f"{v:.2f}" for v in vals})  # what the LLM prompt shows
            worst_churn = max(worst_churn, churn if pct == UNIQUENESS_SAMPLE_PERCENT else 0)
            cells.append(f"{pct:g}%:{min(vals):.2f}..{max(vals):.2f}({churn})")
        print(f"  {table + '.' + col:<38} {nrows:>6} | full={full:.2f}  " + "  ".join(cells))
        if worst_churn > 1:
            findings.append(
                f"{table}.{col}: {worst_churn} distinct prompt renderings at the "
                f"engine's 10% (full-scan value {full:.2f})"
            )
    return findings


def leg4_determinism(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Do seeds actually make each site deterministic — and under threads>1?"""
    print(f"\n  LEG 4 — seeded determinism ({SEED_REPS} reps per cell)")
    findings: list[str] = []
    # representative queries: biggest table for bernoulli; reservoir over the
    # biggest distinct set at the engine's m
    n_je = distinct_stats(conn, "journal_entries", "entry_id")[0]
    m = min(max(MIN_SAMPLE_SIZE, int(n_je * DEFAULT_SAMPLE_RATE)), n_je)
    cases = {
        "bernoulli 10% unseeded": uniqueness_sql("journal_lines", "entry_id", 10.0),
        "bernoulli 10% seed=42": uniqueness_sql("journal_lines", "entry_id", 10.0, seed=42),
        "reservoir unseeded": reservoir_cte(
            "journal_lines", "entry_id", "journal_entries", "entry_id", m, m
        ),
        "reservoir REPEATABLE(42)": reservoir_cte(
            "journal_lines", "entry_id", "journal_entries", "entry_id", m, m, seed=42
        ),
    }
    for threads in (1, 4):
        conn.execute(f"SET threads TO {threads}")
        for name, sql in cases.items():
            results = {str(conn.execute(sql).fetchone()) for _ in range(SEED_REPS)}
            det = "deterministic" if len(results) == 1 else f"{len(results)} DISTINCT RESULTS"
            print(f"    threads={threads}  {name:<28} -> {det}")
            if "seed" in name.lower() or "REPEATABLE" in name:
                if len(results) != 1:
                    findings.append(f"{name} NOT deterministic at threads={threads}")
    conn.execute("SET threads TO 4")
    return findings


def leg5_cost() -> list[str]:
    """Exact vs sampled cost at synthetic scales — where does sampling pay?"""
    print("\n  LEG 5 — exact-vs-sampled cost at synthetic scale (median of 5)")
    findings: list[str] = []
    print(f"    {'distinct':>10} | {'exact jaccard':>13} {'sampled jaccard':>15} "
          f"| {'full uniq':>9} {'10% uniq':>9}")
    for n in (10_000, 100_000, 1_000_000):
        c = duckdb.connect()
        c.execute(f"CREATE TABLE t1 AS SELECT 'v' || range::VARCHAR AS k FROM range({n})")
        c.execute(f"CREATE TABLE t2 AS SELECT 'v' || range::VARCHAR AS k FROM range({n})")

        def timed(sql: str, conn: duckdb.DuckDBPyConnection = c) -> float:
            ts = []
            for _ in range(5):
                t0 = time.perf_counter()
                conn.execute(sql).fetchone()
                ts.append(time.perf_counter() - t0)
            return statistics.median(ts) * 1000

        m = min(max(MIN_SAMPLE_SIZE, int(n * DEFAULT_SAMPLE_RATE)), n)
        t_exact = timed(exact_jaccard_sql("t1", "k", "t2", "k"))
        t_sampled = timed(reservoir_cte("t1", "k", "t2", "k", m, m, seed=42))
        t_full_u = timed(uniqueness_sql("t1", "k", 100.0))
        t_samp_u = timed(uniqueness_sql("t1", "k", 10.0, seed=42))
        print(f"    {n:>10,} | {t_exact:>11.1f}ms {t_sampled:>13.1f}ms "
              f"| {t_full_u:>7.1f}ms {t_samp_u:>7.1f}ms")
        findings.append(f"n={n:,}: exact {t_exact:.1f}ms vs sampled {t_sampled:.1f}ms")
        c.close()
    return findings


def main() -> None:
    print(f"DAT-794 probe — duckdb {duckdb.__version__}, reps={REPS}")
    all_findings: dict[str, list[str]] = {}
    for corpus in CORPORA:
        loaded = load_corpus(corpus)
        if loaded is None:
            continue
        conn, pairs = loaded
        conn.execute("SET threads TO 4")
        print(f"\n{'=' * 78}\nCORPUS: {corpus}  ({len(pairs)} true FK pairs)\n{'=' * 78}")
        sampled = leg1_paths(conn, pairs)
        f2 = leg2_reservoir(conn, sampled) if sampled else []
        if not sampled:
            print("\n  LEG 2 — no pair on the SAMPLED path in this corpus; reservoir "
                  "site cannot affect Layer-A detection here")
        f3 = leg3_uniqueness(conn, pairs)
        f4 = leg4_determinism(conn)
        all_findings[corpus] = [f"[reservoir] {x}" for x in f2] + [
            f"[uniqueness-churn] {x}" for x in f3
        ] + [f"[seeding] {x}" for x in f4]
        conn.close()
    cost = leg5_cost()

    print(f"\n{'=' * 78}\nVERDICT INPUTS\n{'=' * 78}")
    for corpus, fs in all_findings.items():
        print(f"\n  {corpus}:")
        for f in fs or ["  (no instability findings)"]:
            print(f"    - {f}")
    print("\n  cost:")
    for f in cost:
        print(f"    - {f}")


if __name__ == "__main__":
    sys.exit(main())
