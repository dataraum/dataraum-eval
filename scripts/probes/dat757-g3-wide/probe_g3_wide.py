"""DAT-757 /ground gate — does g3 separate TRUE from SPURIOUS FDs on a WIDE table?

CLAIM UNDER TEST (to refute)
----------------------------
"The engine's g3 measure  g3(A->B) = 1 - distinct(A)/distinct(A,B)  (hierarchies/
processor.py:84-88), thresholded at FD_MAX_G3=0.01 with the near-key(0.9) + coarse(>=3)
+ direction(d_a>d_b) guards, cleanly separates true functional dependencies from
spurious (accidentally-valid) ones on a WIDE / denormalized table — so DAT-757 can lean
on it to group a flat fact's OWN columns into folded dimensions."

Prior (Papenbrock; Parciak et al. 2024, "raw g3 separates true-from-spurious poorly"):
FALSE on wide/dirty tables. The engine has only ever run g3 on the NARROW finance corpus,
where the slicing pre-filter (slicing_phase.py:_pre_filter_columns) drops every column
with cardinality_ratio > 0.5 or distinct > 200 BEFORE g3 sees it. That pre-filter — not
g3's own guards — is what has kept g3 safe.

THE ATTACK
----------
DAT-757 scope-decision #2 requires RETAINING folded numerics "by additivity, not
cardinality" (`year`/`store_no`/`rating` must not be dropped as high-cardinality). That
removes the cardinality_ratio>0.5 shield. The dangerous residual is a HEAVY-TAILED
determinant — mostly-unique values plus a few high-frequency "default / bulk / catch-all"
values (operational IDs, document numbers, batch codes on denormalized data). Such a
column reaches card_ratio ~0.6-0.85 (BELOW g3's 0.9 near-key guard, ABOVE the removed 0.5
pre-filter) while still hitting g3<=0.01 against EVERY low-card dimension — because its
singletons are trivially "pure". The engine then asserts confident-wrong drill hierarchies
(`doc_no -> region`, `doc_no -> status`). True FDs (zip->city->state) sit at g3=0 too, so
g3 alone cannot tell them apart once both are in-set: NO MARGIN.

Reliability filter under comparison (the fix): the reliable fraction of information
RFI(A->B) = FI(A->B) - E_perm[FI(A->shuffled B)]  (Mandros-Boley-Vreeken KDD'17; the
chance-corrected information-theoretic ranking Parciak et al. 2024 endorse). For a
heavy-tailed determinant the permutation leaves the singletons pure, so E_perm[FI] ~ FI
and RFI ~ 0 -> correctly rejected. For a true low-card FD the permutation destroys it, so
RFI stays high -> correctly kept.

Run:  uv run python scripts/probes/dat757-g3-wide/probe_g3_wide.py
Pure numpy + duckdb. No docker, no pipeline, no LLM. Milliseconds.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import duckdb

# --- engine constants, copied verbatim from hierarchies/processor.py ---
FD_MAX_G3 = 0.01
MIN_DISTINCT_DIMENSION = 2
MIN_DISTINCT_DETERMINANT = 3
NEAR_KEY_FRAC = 0.9
# slicing_phase.py:_pre_filter_columns — the shield DAT-757 removes for folded numerics
SLICE_CARD_RATIO_MAX = 0.5
SLICE_DISTINCT_MAX = 200

RNG = np.random.default_rng(20260714)


# --------------------------------------------------------------------------- #
# fixture: a wide / denormalized fact                                          #
# --------------------------------------------------------------------------- #
def build_wide_fact(n: int, tail_frac: float) -> dict[str, np.ndarray]:
    """A wide OBT with planted TRUE FDs, independent dims, and one HEAVY-TAILED id.

    tail_frac = fraction of rows pulled into a handful of high-frequency "bulk"
    values of the attack column ``doc_no`` (the rest are unique singletons). Sweeping
    tail_frac moves doc_no's cardinality down from near-key into the exposed band.
    """
    # TRUE FD chain (categorical dimension): zip -> city -> state -> region.
    region = RNG.integers(0, 4, n)                       # 4 regions   (coarsest)
    state = region * 3 + RNG.integers(0, 3, n)           # 12 states   -> region  (true FD)
    city = state * 5 + RNG.integers(0, 5, n)             # ~60 cities  -> state    (true FD)
    zip_ = city * 3 + RNG.integers(0, 3, n)              # ~180 zips   -> city     (true FD)

    # TRUE FD (folded NUMERIC dim DAT-757 must retain): store_no -> store_region.
    store_region = RNG.integers(0, 8, n)
    store_no = store_region * 12 + RNG.integers(0, 12, n)  # ~96 stores -> store_region

    # INDEPENDENT low-card dimensions (no FD to anything).
    status = RNG.integers(0, 5, n)
    channel = RNG.integers(0, 4, n)
    pay_method = RNG.integers(0, 6, n)

    # ATTACK: heavy-tailed operational id. (1-tail_frac) of rows get a unique value;
    # tail_frac of rows share a few "bulk / default" codes. Independent of every dim.
    doc_no = np.arange(n)                                 # start all-unique
    n_tail = int(tail_frac * n)
    if n_tail:
        bulk_codes = np.arange(-1, -11, -1)              # 10 catch-all codes
        tail_idx = RNG.choice(n, size=n_tail, replace=False)
        doc_no[tail_idx] = RNG.choice(bulk_codes, size=n_tail)

    return {
        "region": region, "state": state, "city": city, "zip": zip_,
        "store_region": store_region, "store_no": store_no,
        "status": status, "channel": channel, "pay_method": pay_method,
        "doc_no": doc_no,
    }


# --------------------------------------------------------------------------- #
# measures                                                                     #
# --------------------------------------------------------------------------- #
def g3_engine(con: duckdb.DuckDBPyConnection, a: str, b: str) -> tuple[int, int, int, float]:
    """The engine's distinct-count-ratio g3 (faithful DuckDB replica).

    Returns (d_a, d_b, d_ab, g3(a->b)).  g3 = 1 - d_a/d_ab ; 0 <=> a determines b.
    """
    d_a, d_b, d_ab = con.execute(
        f'SELECT COUNT(DISTINCT "{a}"), COUNT(DISTINCT "{b}"), '
        f'COUNT(DISTINCT ("{a}", "{b}")) FROM w'
    ).fetchone()
    g3 = 0.0 if d_ab == 0 else 1.0 - d_a / d_ab
    return d_a, d_b, d_ab, g3


def g3_rowbased(a: np.ndarray, b: np.ndarray) -> float:
    """Classic Kivinen-Mannila g3 = 1 - (kept tuples)/N, kept = sum_x max_y count(x,y).

    This is the REAL approximate-FD error the engine does NOT compute — shown for contrast.
    """
    order = np.lexsort((b, a))
    a_s, b_s = a[order], b[order]
    n = len(a)
    kept = 0
    i = 0
    while i < n:
        j = i
        while j < n and a_s[j] == a_s[i]:
            j += 1
        # within block a_s[i:j], the largest single-b majority is kept
        _, counts = np.unique(b_s[i:j], return_counts=True)
        kept += counts.max()
        i = j
    return 1.0 - kept / n


def _entropy(counts: np.ndarray) -> float:
    p = counts / counts.sum()
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def fraction_of_information(a: np.ndarray, b: np.ndarray) -> float:
    """FI(a->b) = I(a;b)/H(b) = 1 - H(b|a)/H(b) in [0,1]. 1 <=> a determines b."""
    _, b_counts = np.unique(b, return_counts=True)
    h_b = _entropy(b_counts)
    if h_b == 0:
        return 0.0
    # H(b|a) = sum_a p(a) H(b|a)
    order = np.lexsort((b, a))
    a_s, b_s = a[order], b[order]
    n = len(a)
    h_b_given_a = 0.0
    i = 0
    while i < n:
        j = i
        while j < n and a_s[j] == a_s[i]:
            j += 1
        _, counts = np.unique(b_s[i:j], return_counts=True)
        h_b_given_a += (j - i) / n * _entropy(counts)
        i = j
    return 1.0 - h_b_given_a / h_b


def reliable_fi(a: np.ndarray, b: np.ndarray, reps: int = 80) -> float:
    """RFI = FI(a->b) - mean_perm FI(a->shuffle(b)). Chance-corrected (Mandros-Vreeken)."""
    fi = fraction_of_information(a, b)
    perm = np.empty(reps)
    b_copy = b.copy()
    for r in range(reps):
        RNG.shuffle(b_copy)
        perm[r] = fraction_of_information(a, b_copy)
    return fi - perm.mean()


def engine_asserts(d_a: int, d_b: int, d_ab: int, g3: float, n: int) -> bool:
    """Replicate the engine edge-assertion predicate for a->b (processor.py:466-475)."""
    if g3 > FD_MAX_G3:
        return False
    if not d_a > d_b:                       # finest -> coarsest direction
        return False
    if d_a < MIN_DISTINCT_DETERMINANT:      # too-coarse determinant
        return False
    if n and d_a >= NEAR_KEY_FRAC * n:       # near-key determinant guard
        return False
    return True


def slice_prefilter_keeps(d_a: int, n: int, *, is_enriched: bool) -> bool:
    """slicing_phase.py:_pre_filter_columns — the shield present TODAY."""
    if d_a > SLICE_DISTINCT_MAX:
        return False
    if not is_enriched and d_a / n > SLICE_CARD_RATIO_MAX:
        return False
    return True


# --------------------------------------------------------------------------- #
# legs                                                                         #
# --------------------------------------------------------------------------- #
def main() -> None:
    n = 20_000
    print(f"# DAT-757 g3-on-wide ground gate   (n={n} rows, wide OBT)\n")

    # ---- Leg A: true FDs vs the heavy-tailed determinant, at a realistic tail ----
    cols = build_wide_fact(n, tail_frac=0.35)
    con = duckdb.connect()
    _load(con, cols)

    true_fds = [("zip", "city"), ("city", "state"), ("state", "region"),
                ("store_no", "store_region")]
    spurious = [("doc_no", "status"), ("doc_no", "channel"), ("doc_no", "pay_method")]

    print("## Leg A — per-pair, wide OBT with a heavy-tailed `doc_no` (tail_frac=0.35)")
    print(f"{'pair':28} {'d_a':>6} {'card_a':>6} {'g3_eng':>7} {'g3_row':>7} "
          f"{'FI':>5} {'RFI':>6} {'ENGINE?':>8} {'shield':>7}")
    header = None
    for label, pairs in (("TRUE FD", true_fds), ("SPURIOUS", spurious)):
        for a, b in pairs:
            d_a, d_b, d_ab, g3e = g3_engine(con, a, b)
            g3r = g3_rowbased(cols[a], cols[b])
            fi = fraction_of_information(cols[a], cols[b])
            rfi = reliable_fi(cols[a], cols[b])
            asserted = engine_asserts(d_a, d_b, d_ab, g3e, n)
            # folded numeric retained by DAT-757 => is_enriched-style exemption
            shield = slice_prefilter_keeps(d_a, n, is_enriched=False)
            tag = f"[{label}]"
            print(f"{tag:8}{a+'->'+b:20} {d_a:>6} {d_a/n:>6.3f} {g3e:>7.4f} {g3r:>7.4f} "
                  f"{fi:>5.2f} {rfi:>6.3f} {'ASSERT' if asserted else '  -':>8} "
                  f"{'keeps' if shield else 'DROPS':>7}")

    # ---- Leg B: sweep the tail — does g3's OWN guard-set (no slice shield) hold? ----
    print("\n## Leg B — sweep doc_no tail_frac. Which measure asserts the SPURIOUS doc_no->status?")
    print("   (g3_eng = engine distinct-ratio ; g3_row = classic Kivinen-Manilla ; both @<=0.01)")
    print(f"{'tail':>5} {'d_doc':>7} {'card':>6} {'g3_eng':>8} {'g3_row':>8} {'RFI':>7} "
          f"{'eng?':>6} {'row?':>6} {'nearkey':>8} {'slice>200':>10}")
    for tail in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.97]:
        c = build_wide_fact(n, tail_frac=tail)
        _load(con, c)
        d_a, d_b, d_ab, g3e = g3_engine(con, "doc_no", "status")
        g3r = g3_rowbased(c["doc_no"], c["status"])
        rfi = reliable_fi(c["doc_no"], c["status"], reps=40)
        eng = engine_asserts(d_a, d_b, d_ab, g3e, n)
        row = engine_asserts(d_a, d_b, d_ab, g3r, n)          # same guards, row-based error
        nearkey = d_a >= NEAR_KEY_FRAC * n
        shielded = not slice_prefilter_keeps(d_a, n, is_enriched=False)
        print(f"{tail:>5.2f} {d_a:>7} {d_a/n:>6.3f} {g3e:>8.5f} {g3r:>8.5f} {rfi:>7.3f} "
              f"{'YES' if eng else '-':>6} {'YES' if row else '-':>6} "
              f"{'GUARD' if nearkey else '-':>8} {'DROP' if shielded else 'keep':>10}")

    # ---- Leg C: decision-level separation (does the THRESHOLD discriminate?) ----
    print("\n## Leg C — GAP: can each measure's DECISION tell TRUE from SPURIOUS? (tail=0.35)")
    c = build_wide_fact(n, tail_frac=0.35)
    _load(con, c)

    def decisions(pairs):
        out = []
        for a, b in pairs:
            d_a, d_b, d_ab, g3e = g3_engine(con, a, b)
            g3r = g3_rowbased(c[a], c[b])
            rfi = reliable_fi(c[a], c[b])
            out.append({
                "pair": f"{a}->{b}", "card_a": d_a / n,
                "g3_eng": g3e, "eng_assert": engine_asserts(d_a, d_b, d_ab, g3e, n),
                "g3_row": g3r, "row_assert": engine_asserts(d_a, d_b, d_ab, g3r, n),
                "rfi": rfi,
            })
        return out

    td, sd = decisions(true_fds), decisions(spurious)
    for name, key in (("g3_eng (engine today)", "eng_assert"),
                      ("g3_row (classic g3)", "row_assert")):
        t_hit = sum(d[key] for d in td)
        s_hit = sum(d[key] for d in sd)
        ok = t_hit == len(td) and s_hit == 0
        print(f"  {name:24}: asserts {t_hit}/{len(td)} TRUE, {s_hit}/{len(sd)} SPURIOUS "
              f"-> {'SEPARATES' if ok else 'FAILS (spurious asserted)' if s_hit else 'misses true'}")
    t_rfi_min = min(d["rfi"] for d in td)
    s_rfi_max = max(d["rfi"] for d in sd)
    rfi_ok = t_rfi_min > s_rfi_max
    print(f"  {'RFI (info-theoretic)':24}: TRUE min={t_rfi_min:.3f}  SPURIOUS max={s_rfi_max:.3f}  "
          f"-> {'SEPARATES (gap %.3f)' % (t_rfi_min - s_rfi_max) if rfi_ok else 'OVERLAP'}")

    # ---- verdict ----
    print("\n## VERDICT")
    eng_fails = sum(d["eng_assert"] for d in sd) > 0
    row_ok = sum(d["row_assert"] for d in sd) == 0 and sum(d["row_assert"] for d in td) == len(td)
    print(f"  engine g3 (distinct-ratio) asserts spurious hierarchies on wide data? "
          f"{'YES -> FAILS' if eng_fails else 'no'}")
    print(f"  ... near-key(0.9) guard catches the heavy-tailed doc_no?  "
          f"NO (fires at card 0.2-0.85, under the 0.9 guard)")
    print(f"  ... only shield today = slicing distinct>200 / card>0.5 pre-filter "
          f"(which DAT-757 widening relaxes)")
    print(f"  classic row-based g3 separates?   {'YES' if row_ok else 'no'}")
    print(f"  RFI info-theoretic filter separates? {'YES' if rfi_ok else 'no'}")
    if eng_fails and (row_ok or rfi_ok):
        print("\n  => CUT 'engine g3 as-is is safe for folded grouping'. Its distinct-count-ratio\n"
              "     understates FD error on heavy-tailed determinants and its guards do NOT abstain\n"
              "     on degenerate operational IDs (DAT-757 scope #3 assumes the near-key guard does).\n"
              "     A reliability filter is REQUIRED before the folded-candidate widening: either the\n"
              "     classic row-based g3 (cheap) or RFI / info-theoretic ranking (Parciak 2024).")


def _load(con: duckdb.DuckDBPyConnection, cols: dict[str, np.ndarray]) -> None:
    """Materialize the fixture as table ``w`` so COUNT(DISTINCT (a,b)) matches the engine."""
    df = pl.DataFrame({k: v for k, v in cols.items()})  # noqa: F841 — read by duckdb below
    con.execute("DROP TABLE IF EXISTS w")
    con.execute("CREATE TABLE w AS SELECT * FROM df")


if __name__ == "__main__":
    main()
