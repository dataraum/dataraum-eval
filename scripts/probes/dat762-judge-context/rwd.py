"""RWD benchmark loader — Parciak et al., Zenodo record 8098909 (CC-BY-4.0).

"Annotated Benchmark of Real-World Data for Approximate Functional Dependency
Discovery". Tables + annotation CSVs live in ``corpora/rwd/`` (gitignored); they are
byte-identical to the Zenodo originals (MD5-verified on download).

Two facts about the raw data that this module normalises, both verified against
the published files rather than assumed:

1. **Column-name normalisation.** ``ground_truth.csv`` / ``*_candidates.csv``
   reference columns by a *normalised* name: whitespace and parentheses stripped.
   The raw headers do not match those tokens literally --
   ``Provider Number(String)`` -> ``ProviderNumberString``, ``Airport Code`` ->
   ``AirportCode``, and ``adult.csv`` is ``", "``-separated so every header after
   the first carries a leading space (`` workclass`` -> ``workclass``).
   Without this, 72/142 ground-truth rows appear to dangle. With it: zero dangle
   across all three annotation files. Normalisation is collision-free on all 9
   tables (asserted at load).

2. **Trailing blank line.** ``adult.csv`` (alone among the 9) ends with a double
   newline; a naive read yields a spurious all-null 32562nd row. Dropped here,
   giving the canonical UCI count of 32561.

Note on the filename row-encoding: ``r72738_c18`` counts **total lines including
the header**, so the table holds 72737 data rows. This is a naming convention,
not clipping -- ``wc -l`` equals the encoded ``r`` exactly for all four biocase
tables, and the files match Zenodo's MD5.

The exact slice (g3 == 1.0) is invariant to a discrepancy worth recording: the
Zenodo ``included_candidates.csv`` carries a ``g3_prime`` column, while some
locally-derived copies carry a recomputed ``g3``. The two disagree on which
*approximate* candidates fall inside the annotation threshold (92 rows shift
between included/excluded), but the ``== 1.0`` slices are identical sets --
390 candidates, 126 meaningful, under either column. Both names are accepted.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

import polars as pl

DATA_DIR = Path(__file__).resolve().parents[3] / "corpora" / "rwd"

TABLES: tuple[str, ...] = (
    "adult.csv",
    "claims.csv",
    "dblp10k.csv",
    "hospital.csv",
    "tax.csv",
    "t_biocase_gathering_agent_r72738_c18.csv",
    "t_biocase_gathering_namedareas_r137711_c11.csv",
    "t_biocase_gathering_r90992_c35.csv",
    "t_biocase_identification_r91800_c38.csv",
)

# Pre-registered invariants of the exact slice. Asserted, never inferred.
EXPECTED_EXACT = 390
EXPECTED_MEANINGFUL = 126


def normalise(column: str) -> str:
    """Map a raw CSV header to the token used in the annotation files."""
    return column.strip().replace("(", "").replace(")", "").replace(" ", "")


@lru_cache(maxsize=None)
def load_table(name: str) -> pl.DataFrame:
    """Load one benchmark table, columns normalised. Cached."""
    if name not in TABLES:
        raise KeyError(f"{name!r} is not an RWD benchmark table; expected one of {TABLES}")
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing. Fetch from https://zenodo.org/records/8098909 into {DATA_DIR}."
        )

    df = pl.read_csv(path, infer_schema_length=0)

    # adult.csv's trailing blank line parses as an all-null row.
    if df.height and all(v is None for v in df.row(df.height - 1)):
        df = df.head(df.height - 1)

    df = df.rename({c: normalise(c) for c in df.columns})

    if len(set(df.columns)) != df.width:
        raise AssertionError(f"{name}: column normalisation collided -> {df.columns}")
    if df.height == 0 or df.width == 0:
        raise AssertionError(f"{name}: loaded empty ({df.height}x{df.width})")
    return df


def _read_annotation(filename: str) -> list[dict[str, str]]:
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing. Fetch from https://zenodo.org/records/8098909 into {DATA_DIR}."
        )
    with path.open() as fh:
        return list(csv.DictReader(fh))


@lru_cache(maxsize=1)
def ground_truth() -> frozenset[tuple[str, str, str]]:
    """(table, lhs, rhs) triples annotated as semantically meaningful."""
    return frozenset(
        (r["table"], r["lhs"], r["rhs"]) for r in _read_annotation("ground_truth.csv")
    )


@lru_cache(maxsize=1)
def exact_candidates() -> list[dict]:
    """The 390-row exact slice: included candidates with g3 == 1.0 and empty != True.

    ``meaningful`` is the ground-truth label -- True iff the pair was annotated as
    semantically implied. Fails loudly if the slice is not exactly 390/126.
    """
    rows = _read_annotation("included_candidates.csv")
    if not rows:
        raise AssertionError("included_candidates.csv is empty")

    header = rows[0].keys()
    g3_col = next((c for c in ("g3", "g3_prime") if c in header), None)
    if g3_col is None:
        raise AssertionError(f"no g3/g3_prime column in included_candidates.csv: {list(header)}")

    truth = ground_truth()
    out: list[dict] = []
    for r in rows:
        if r["empty"].strip().lower() == "true":
            continue
        try:
            g3 = float(r[g3_col])
        except (TypeError, ValueError):
            continue
        if g3 != 1.0:
            continue
        key = (r["table"], r["lhs"], r["rhs"])
        out.append({"table": key[0], "lhs": key[1], "rhs": key[2], "meaningful": key in truth})

    n_meaningful = sum(c["meaningful"] for c in out)
    if len(out) != EXPECTED_EXACT or n_meaningful != EXPECTED_MEANINGFUL:
        raise AssertionError(
            f"exact slice is {len(out)} rows / {n_meaningful} meaningful; "
            f"expected {EXPECTED_EXACT}/{EXPECTED_MEANINGFUL} "
            f"(g3 column used: {g3_col!r})"
        )

    # Every candidate must reference real columns in a table we actually have.
    for c in out:
        cols = load_table(c["table"]).columns
        for side in ("lhs", "rhs"):
            if c[side] not in cols:
                raise AssertionError(f"{c['table']}: {side}={c[side]!r} not a column")
    return out


if __name__ == "__main__":
    cands = exact_candidates()
    print(f"exact slice: {len(cands)} candidates, {sum(c['meaningful'] for c in cands)} meaningful")
    for t in TABLES:
        df = load_table(t)
        print(f"  {t:50s} {df.height:>8,} x {df.width:>2}")
