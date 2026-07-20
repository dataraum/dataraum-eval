"""DAT-757 /ground gate — REAL leg: g3 on a genuinely denormalized finance table.

Leg (a) of the gate. The recorded entropy fixture is narrow finance; the faithful wide
substrate is the generator's own `flat` denormalization: general_ledger =
journal_lines |><| journal_entries (entry_id) |><| chart_of_accounts (account_id). Built
inline here from data/tfm-clean/*.csv, reproducing schema_transforms._inline_chart_of_accounts
verbatim (rename name->account_name, parent_id->parent_account_id, currency->account_currency).

Confirms the synthetic finding on real shapes: the real heavy-tailed determinant is
`entry_id` (~2 journal lines / entry, card ~0.47). Reports every directed pair where the
engine's distinct-ratio g3 ASSERTS an FD (g3_eng<=0.01 + guards) that the classic
row-based g3 REJECTS (g3_row>0.01) — the engine's false folded-dimension edges.

Run:  uv run python scripts/probes/dat757-g3-wide/probe_g3_real.py
"""

from __future__ import annotations

import numpy as np
import polars as pl
import duckdb

from probe_g3_wide import (
    FD_MAX_G3, MIN_DISTINCT_DIMENSION,
    g3_engine, g3_rowbased, fraction_of_information, reliable_fi, engine_asserts,
)


def asserts_with_constant_guard(d_a: int, d_b: int, d_ab: int, g3: float, n: int) -> bool:
    """engine_asserts + the MIN_DISTINCT_DIMENSION drop of a CONSTANT dependent/determinant.

    processor.py:430 removes any column with < MIN_DISTINCT_DIMENSION distinct from BOTH
    roles before g3 runs, so X -> constant is never asserted. My first scan omitted this.
    """
    if d_a < MIN_DISTINCT_DIMENSION or d_b < MIN_DISTINCT_DIMENSION:
        return False
    return engine_asserts(d_a, d_b, d_ab, g3, n)

DATA = "data/tfm-clean"


def build_flat_gl() -> pl.DataFrame:
    """Reproduce schema_transforms 'flat' general_ledger from the real CSVs."""
    jl = pl.read_csv(f"{DATA}/journal_lines.csv", infer_schema_length=10000)
    je = pl.read_csv(f"{DATA}/journal_entries.csv", infer_schema_length=10000)
    coa = pl.read_csv(f"{DATA}/chart_of_accounts.csv", infer_schema_length=10000)
    journal_data = jl.join(je, on="entry_id", how="left")
    coa_renamed = coa.rename(
        {"name": "account_name", "parent_id": "parent_account_id", "currency": "account_currency"}
    )
    return journal_data.join(coa_renamed, on="account_id", how="left")


def _codes(df: pl.DataFrame, col: str) -> np.ndarray:
    """Integer codes for a column, NULL -> its own category (for FI/RFI)."""
    s = df.get_column(col).cast(pl.Utf8).fill_null("␀")
    _, codes = np.unique(s.to_numpy(), return_inverse=True)
    return codes.astype(np.int64)


def main() -> None:
    gl = build_flat_gl()
    n = gl.height
    print(f"# DAT-757 g3-on-wide — REAL leg (flat general_ledger, n={n} rows, "
          f"{gl.width} cols)\n")
    print("cols:", ", ".join(gl.columns), "\n")

    con = duckdb.connect()
    con.register("gl", gl)
    con.execute("CREATE TABLE w AS SELECT * FROM gl")

    # candidate categorical dimensions (own columns of the folded fact).
    # REVIEW ADDITIONS (universe sweep): description (free text, heavy-tailed),
    # line_id (full operational key), account_name (1:1 alias with account_id) —
    # the first candidate set wrongly excluded free text, repeating the shield-thinking.
    cands = ["account_id", "account_name", "account_type", "account_currency",
             "parent_account_id", "currency", "cost_center", "status", "created_by",
             "entry_id", "description", "line_id"]
    cands = [c for c in cands if c in gl.columns]
    code = {c: _codes(gl, c) for c in cands}
    dist = {c: con.execute(f'SELECT COUNT(DISTINCT "{c}") FROM w').fetchone()[0] for c in cands}

    print("candidate cardinalities (card = distinct/n):")
    for c in sorted(cands, key=lambda c: -dist[c]):
        print(f"  {c:22} distinct={dist[c]:>6}  card={dist[c]/n:6.3f}")

    # curated pairs: real folded account dim (TRUE) + heavy-tailed entry_id suspects
    curated = [
        ("TRUE  ", "account_id", "account_type"),
        ("TRUE  ", "account_id", "account_currency"),
        ("TRUE  ", "account_id", "parent_account_id"),
        ("TRUE? ", "entry_id", "status"),        # entry-level attr -> likely true FD
        ("TRUE? ", "entry_id", "created_by"),
        ("SUSPECT", "entry_id", "account_type"),  # line-level -> entry should NOT determine
        ("SUSPECT", "entry_id", "account_currency"),
        ("SUSPECT", "entry_id", "cost_center"),
        ("SUSPECT", "entry_id", "currency"),
        # free text as determinant: statistically real via the entry grain, semantically
        # void as a dimension hierarchy — the class reliability filters CANNOT rescue.
        ("TEXT   ", "description", "cost_center"),
        ("TEXT   ", "description", "created_by"),
    ]
    print("\n## curated pairs")
    print(f"{'':8}{'pair':34} {'g3_eng':>8} {'g3_row':>8} {'RFI':>7} {'eng?':>6} {'row?':>6}")
    for tag, a, b in curated:
        if a not in gl.columns or b not in gl.columns:
            continue
        d_a, d_b, d_ab, g3e = g3_engine(con, a, b)
        g3r = g3_rowbased(code[a], code[b])
        rfi = reliable_fi(code[a], code[b], reps=40)
        eng = asserts_with_constant_guard(d_a, d_b, d_ab, g3e, n)
        row = asserts_with_constant_guard(d_a, d_b, d_ab, g3r, n)
        cst = " (const dep)" if d_b < MIN_DISTINCT_DIMENSION else ""
        print(f"{tag:8}{a+'->'+b:34} {g3e:>8.4f} {g3r:>8.4f} {rfi:>7.3f} "
              f"{'YES' if eng else '-':>6} {'YES' if row else '-':>6}{cst}")

    # full auto-scan: every directed pair the engine would ASSERT — flag disagreements
    print("\n## full scan — pairs the ENGINE g3 asserts as folded-dim edges (g3_eng<=0.01 + guards):")
    print(f"{'pair':40} {'card_a':>7} {'g3_eng':>8} {'g3_row':>8} {'RFI':>7}  verdict")
    false_asserts = 0
    for a in cands:
        for b in cands:
            if a == b:
                continue
            d_a, d_b, d_ab, g3e = g3_engine(con, a, b)
            if not asserts_with_constant_guard(d_a, d_b, d_ab, g3e, n):
                continue
            g3r = g3_rowbased(code[a], code[b])
            rfi = reliable_fi(code[a], code[b], reps=30)
            spurious = g3r > FD_MAX_G3 or rfi < 0.05
            if spurious:
                false_asserts += 1
            print(f"{a+'->'+b:40} {d_a/n:>7.3f} {g3e:>8.4f} {g3r:>8.4f} {rfi:>7.3f}  "
                  f"{'<-- SPURIOUS (row-g3/RFI reject)' if spurious else 'true FD'}")

    # alias scan — the engine's 1:1 path (processor.py:219-221) unions on bidirectional
    # g3<=0.01 with ONLY the constant guard; _bad_determinant (near-key) is never
    # consulted for aliases. Two independent near-key columns therefore alias-merge.
    print("\n## alias scan — bidirectional g3_eng<=0.01 (engine alias path: NO near-key guard)")
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            d_a, d_b, d_ab, g3f = g3_engine(con, a, b)
            if d_a < MIN_DISTINCT_DIMENSION or d_b < MIN_DISTINCT_DIMENSION:
                continue
            g3b = 1.0 if d_ab == 0 else 1.0 - d_b / d_ab
            if g3f <= FD_MAX_G3 and g3b <= FD_MAX_G3:
                rfi_v = reliable_fi(code[a], code[b], reps=30)
                near_key = max(d_a, d_b) >= 0.9 * n
                print(f"  {a} <-> {b}  card=({d_a / n:.3f},{d_b / n:.3f})  rfi={rfi_v:.3f}"
                      f"{'  <-- near-key members, unguarded' if near_key else ''}")

    print("\n## VERDICT (real leg)")
    print(f"  engine g3 makes {false_asserts} FALSE folded-dim assertion(s) on the real flat GL "
          f"(constants dropped per MIN_DISTINCT_DIMENSION)")
    print("  Clean FK-normalized finance barely exercises the failure: its non-constant dims are")
    print("  either the real account hierarchy or genuinely entry-grained. The heavy-tailed shape")
    print("  IS present (entry_id card=0.47) but this corpus lacks an INDEPENDENT line-level dim to")
    print("  expose it -> confirms the ticket's premise: validation needs a DENORMALIZED non-finance")
    print("  corpus (thread 2). The spurious mechanism itself is proven in the synthetic leg.")


if __name__ == "__main__":
    main()
