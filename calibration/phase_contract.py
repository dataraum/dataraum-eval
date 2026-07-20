"""Per-phase output contract for ``add_source`` — what each phase MUST produce.

Philipp, 2026-07-20: *"Just defining what outcome to expect from a specific dataset
is enough… run it once and know for EACH phase what output it MUST produce to be
correct. Tweaking datasets is easier, testing towards a known result set is hard."*

So this is the hard thing, on one small corpus. ``add_source`` is ten phases —
``import``, ``check_column_limit``, then per table ``typing`` / ``statistics`` /
``column_eligibility`` / ``statistical_quality`` / ``temporal``, then source-wide
``semantic_per_column``, ``detect``, ``promote_to_latest``. Eight are deterministic,
and for those the expected output is **derivable from the source file** rather than
hand-authored: DuckDB over the parquet is a second implementation of the same
question, so a divergence is a real defect and not a stale recording.

That distinction is the point. A golden file records what the engine did and
freezes it — it can only ever catch change, never error. These expectations are
computed from the data independently, so they can catch an engine that has been
wrong since the day it was written. ``TIMESTAMP_NS`` (DAT-835) is the worked
example: every one of rel-f1's six declared time columns is absent from the
temporal phase, and the contract names them per column instead of leaving it in a
``phase_skipped`` log line nobody reads.

What is NOT derivable stays out: ``semantic_per_column``'s roles are a human
declaration (a customer framing their own data) and belong in the corpus's
``metadata_truth.yaml``, not here.

    uv run python -m calibration.phase_contract rel-f1
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EVAL_ROOT = Path(__file__).parent.parent
CORPORA_DIR = EVAL_ROOT / "corpora" / "relbench"

# The temporal phase's whitelist (engine `temporal_phase.py:64`). Kept here as the
# CONTRACT's own statement of what a time column is, deliberately NOT imported from
# the engine: an oracle that reads the implementation it grades cannot disagree with
# it. DuckDB names nanosecond parquet timestamps TIMESTAMP_NS, which is exactly the
# gap DAT-835 records.
TEMPORAL_TYPES = {"DATE", "TIMESTAMP", "TIMESTAMPTZ", "TIMESTAMP_NS", "TIMESTAMP_MS", "TIMESTAMP_S"}

NUMERIC_TYPES = {
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "FLOAT",
    "DOUBLE",
    "REAL",
    "DECIMAL",
}


@dataclass
class PhaseScore:
    """One phase's grade: how many cells were checked, and which diverged."""

    phase: str
    checked: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.misses

    def line(self) -> str:
        mark = "OK  " if self.ok else "MISS"
        detail = f" ({len(self.misses)} miss)" if self.misses else ""
        return (
            f"  [{mark}] {self.phase:<22} {self.checked - len(self.misses)}/{self.checked}{detail}"
        )


def _norm_type(duckdb_type: str) -> str:
    """DuckDB's type name, stripped of parameters (``DECIMAL(18,3)`` → ``DECIMAL``)."""
    return duckdb_type.split("(")[0].strip().upper()


def derive_expectations(dataset: str) -> dict[str, Any]:
    """Compute, from the parquet files alone, what add_source MUST produce.

    A second implementation of the same questions the engine answers — never a
    read of the engine's own output.
    """
    import duckdb

    src = CORPORA_DIR / dataset
    schema = json.loads((src / "schema.json").read_text())
    conn = duckdb.connect()

    tables: dict[str, dict[str, Any]] = {}
    for parquet in sorted((src / "tables").glob("*.parquet")):
        table = parquet.stem.lower()
        path = str(parquet).replace("'", "''")
        described = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()
        rows = conn.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()
        n_rows = int(rows[0]) if rows else 0

        cols: dict[str, dict[str, Any]] = {}
        for name, dtype, *_ in described:
            col = str(name).lower()
            t = _norm_type(str(dtype))
            q = conn.execute(  # noqa: S608 — identifiers come from the file's own schema
                f'SELECT count(*) - count("{name}"), count(DISTINCT "{name}") '
                f"FROM read_parquet('{path}')"
            ).fetchone()
            nulls, distinct = (int(q[0]), int(q[1])) if q else (0, 0)
            null_ratio = (nulls / n_rows) if n_rows else 0.0
            cardinality = (distinct / n_rows) if n_rows else 0.0
            cols[col] = {
                "type": t,
                "distinct_count": distinct,
                "null_ratio": null_ratio,
                "cardinality_ratio": cardinality,
                "is_numeric": t in NUMERIC_TYPES,
                "is_temporal": t in TEMPORAL_TYPES,
                "eligibility": _eligibility(null_ratio, distinct, cardinality),
            }
        tables[table] = {"row_count": n_rows, "columns": cols}

    conn.close()
    return {"dataset": dataset, "declared": schema, "tables": tables}


def _eligibility(null_ratio: float, distinct: int, cardinality: float) -> str:
    """The four ordered rules of ``phases/column_eligibility.yaml``, first match wins.

    Restated here rather than imported, for the same reason as TEMPORAL_TYPES: an
    oracle that calls the code under test proves only that the code equals itself.
    Thresholds: max_null_ratio 1.0, warn_null_ratio 0.5, warn_single_value true.
    """
    if null_ratio >= 1.0:
        return "INELIGIBLE"
    if distinct == 1:
        return "WARN"
    if null_ratio > 0.5:
        return "WARN"
    if cardinality < 0.01 and distinct <= 3:
        return "WARN"
    return "ELIGIBLE"


def read_actuals(strategy: str) -> dict[str, Any]:
    """What the engine actually produced for this strategy's completed run."""
    from sqlalchemy import text

    from calibration import runner
    from calibration.tools._runs import short, workspace_session

    runner.activate_workspace(strategy)
    out: dict[str, Any] = {"tables": {}, "temporal_columns": set(), "quality_columns": set()}

    with workspace_session() as session:
        for tid, name, layer, rc in session.execute(
            text("SELECT table_id, table_name, layer, row_count FROM tables")
        ).all():
            if layer != "typed":
                continue
            out["tables"][short(str(name)).lower()] = {"table_id": tid, "row_count": rc}

        rows = session.execute(
            text(
                "SELECT t.table_name, c.column_name, c.resolved_type, c.column_id, "
                "p.distinct_count, p.null_ratio, p.cardinality_ratio "
                "FROM columns c JOIN tables t ON t.table_id = c.table_id "
                "LEFT JOIN statistical_profiles p ON p.column_id = c.column_id "
                "WHERE t.layer = 'typed'"
            )
        ).all()
        cols: dict[tuple[str, str], dict[str, Any]] = {}
        for tname, cname, rtype, cid, distinct, nullr, card in rows:
            cols[(short(str(tname)).lower(), str(cname).lower())] = {
                "type": _norm_type(str(rtype or "")),
                "column_id": cid,
                "distinct_count": distinct,
                "null_ratio": nullr,
                "cardinality_ratio": card,
            }
        out["columns"] = cols

        for tbl, key in (("column_eligibility", "status"), ("statistical_quality_metrics", None)):
            try:
                if key:
                    out["eligibility"] = {
                        str(r[0]): str(r[1])
                        for r in session.execute(
                            text(f"SELECT column_id, {key} FROM {tbl}")  # noqa: S608
                        ).all()
                    }
                else:
                    out["quality_columns"] = {
                        str(r[0])
                        for r in session.execute(text(f"SELECT column_id FROM {tbl}")).all()  # noqa: S608
                    }
            except Exception:  # noqa: BLE001 — absence is a finding, reported as 0 coverage
                out.setdefault("eligibility", {})

        try:
            out["temporal_columns"] = {
                str(r[0])
                for r in session.execute(
                    text("SELECT DISTINCT column_id FROM temporal_column_profiles")
                ).all()
            }
        except Exception:  # noqa: BLE001 — table may not exist; graded as zero coverage
            out["temporal_columns"] = set()

    return out


def grade(dataset: str, strategy: str | None = None) -> list[PhaseScore]:
    """Grade every derivable add_source phase, one score per phase."""
    exp = derive_expectations(dataset)
    act = read_actuals(strategy or dataset)
    scores: list[PhaseScore] = []

    # --- import: every declared table present, with its exact row count ---
    s = PhaseScore("import")
    for tname, spec in sorted(exp["tables"].items()):
        s.checked += 1
        got = act["tables"].get(tname)
        if got is None:
            s.misses.append(f"{tname}: table absent from the typed layer")
        elif got["row_count"] != spec["row_count"]:
            s.misses.append(f"{tname}: {got['row_count']} rows, expected {spec['row_count']}")
    scores.append(s)

    # --- typing: every column's resolved type equals the parquet's declared type ---
    s = PhaseScore("typing")
    for tname, spec in sorted(exp["tables"].items()):
        for cname, c in sorted(spec["columns"].items()):
            s.checked += 1
            got = act["columns"].get((tname, cname))
            if got is None:
                s.misses.append(f"{tname}.{cname}: column absent")
            elif got["type"] != c["type"]:
                s.misses.append(f"{tname}.{cname}: typed {got['type']}, declared {c['type']}")
    scores.append(s)

    # --- statistics: distinct_count / null_ratio recomputed independently ---
    s = PhaseScore("statistics")
    for tname, spec in sorted(exp["tables"].items()):
        for cname, c in sorted(spec["columns"].items()):
            got = act["columns"].get((tname, cname))
            if got is None or got["distinct_count"] is None:
                continue  # absence is typing's finding, not statistics'
            s.checked += 1
            if int(got["distinct_count"]) != c["distinct_count"]:
                s.misses.append(
                    f"{tname}.{cname}: distinct {got['distinct_count']}, expected {c['distinct_count']}"
                )
            elif abs(float(got["null_ratio"] or 0) - c["null_ratio"]) > 1e-6:
                s.misses.append(
                    f"{tname}.{cname}: null_ratio {float(got['null_ratio'] or 0):.6f}, "
                    f"expected {c['null_ratio']:.6f}"
                )
    scores.append(s)

    # --- column_eligibility: the four ordered rules, applied independently ---
    s = PhaseScore("column_eligibility")
    elig = act.get("eligibility") or {}
    for tname, spec in sorted(exp["tables"].items()):
        for cname, c in sorted(spec["columns"].items()):
            got = act["columns"].get((tname, cname))
            if got is None:
                continue
            s.checked += 1
            actual = elig.get(str(got["column_id"]))
            if actual is None:
                s.misses.append(f"{tname}.{cname}: no eligibility verdict recorded")
            elif actual != c["eligibility"]:
                s.misses.append(f"{tname}.{cname}: {actual}, expected {c['eligibility']}")
    scores.append(s)

    # --- temporal: every temporal-typed column must be profiled as one ---
    s = PhaseScore("temporal")
    for tname, spec in sorted(exp["tables"].items()):
        for cname, c in sorted(spec["columns"].items()):
            if not c["is_temporal"]:
                continue
            s.checked += 1
            got = act["columns"].get((tname, cname))
            if got is None or str(got["column_id"]) not in act["temporal_columns"]:
                s.misses.append(f"{tname}.{cname} ({c['type']}): not profiled as temporal")
    scores.append(s)

    # --- statistical_quality: every numeric column must be assessed ---
    s = PhaseScore("statistical_quality")
    for tname, spec in sorted(exp["tables"].items()):
        for cname, c in sorted(spec["columns"].items()):
            if not c["is_numeric"]:
                continue
            s.checked += 1
            got = act["columns"].get((tname, cname))
            if got is None or str(got["column_id"]) not in act["quality_columns"]:
                s.misses.append(f"{tname}.{cname} ({c['type']}): no quality metrics")
    scores.append(s)

    # --- promote_to_latest: one typed head per declared table ---
    s = PhaseScore("promote_to_latest")
    s.checked = 1
    if len(act["tables"]) != len(exp["tables"]):
        s.misses.append(f"{len(act['tables'])} typed heads, expected {len(exp['tables'])}")
    scores.append(s)

    return scores


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dataset", help="corpus under corpora/relbench/ (e.g. rel-f1)")
    ap.add_argument("--strategy", help="staged strategy name (default: same as dataset)")
    ap.add_argument("--verbose", "-v", action="store_true", help="list every miss")
    args = ap.parse_args()

    scores = grade(args.dataset, args.strategy)
    print(f"\n=== add_source phase contract — {args.dataset} ===")
    for sc in scores:
        print(sc.line())
        if sc.misses:
            for m in sc.misses[: (None if args.verbose else 6)]:
                print(f"          {m}")
            if not args.verbose and len(sc.misses) > 6:
                print(f"          … {len(sc.misses) - 6} more (use -v)")
    bad = [s.phase for s in scores if not s.ok]
    print(
        f"\n  → {'ALL PHASES MEET CONTRACT' if not bad else 'CONTRACT VIOLATED: ' + ', '.join(bad)}"
    )


if __name__ == "__main__":
    main()
