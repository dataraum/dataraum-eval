"""DAT-757 adversarial round — attack the FROZEN mixed gate off its derivation fixture.

CLAIM UNDER TEST (to refute)
----------------------------
"The mixed gate's 32/32 (edges: row-g3+RFI; aliases: pair-count-g3+RFI; thresholds
0.01 / 0.05 pre-registered, untuned) generalizes beyond the fixture it was derived on."

Bias being tested (named before running): (1) mixed was SELECTED on the same 40 cells it
scored 32/32 on; (2) the matrix fixture attacks the OLD algorithm's threat model, not
mixed's — RFI's chance-correction depends on group size n/d, so behavior is tied to the
cardinality ratio and my single n; (3) RFI is conservative by design (greedy): it can
remove TRUE fine-grained candidates. mixed is FROZEN — failures below become the boundary
map, never a retune (a second fished attempt is banned).

THE ATTACKS
-----------
A seed sweep      — same cells, 5 fresh seeds: is 32/32 sampling luck?
B n sweep         — n in {500, 2000, 20000}: which decisions flip with table size?
C card sweep      — TRUE FD det(card c) -> dep(24), c in .05...85: where does RFI start
                    killing REAL fine-grained determinants? (the greediness boundary)
D dirt sweep      — TRUE FD with f in {0.5,1,2,5}% corrupted rows: row-g3's 0.01 FN edge
                    (the A4 axis the matrix under-built: it planted only 0.015%)
E skewed dependent— B with dominant value p_min in {5,1,0.5}% minority vs independent
                    determinants (heavy-tail id / mid-card uniform) + a true control:
                    row-g3 asserts ANYTHING onto a skewed flag once minority < 1% — my
                    balanced 50/50 flags hid this; is RFI the only thing standing?
F alias chaining  — union-find transitivity: near-duplicate dirty copies B~C~D of one
                    dim, each adjacent pair-g3 <= 0.01 but A-D > 0.01: does the group
                    over-merge greedily? (plus the cross-dim impossibility argument)

Run:  uv run python scripts/probes/dat757-g3-wide/probe_adversarial.py   (repo root, ~1 min)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from fdlib import alias_decision, edge_decision, rfi_of, scan_pairs  # noqa: E402
from probe_matrix import CELLS, GATES, N, build_fact_a, build_fact_b, decide  # noqa: E402

STRUCTURAL = [c for c in CELLS if c.lane == "structural"]


def score_structural(seed: int, n: int, n_b: int) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    df_a = build_fact_a(rng, n)
    df_b = build_fact_b(rng, n_b)
    scan_a = scan_pairs(df_a, df_a.columns)
    scan_b = scan_pairs(df_b, df_b.columns)
    out: dict[str, int] = {}
    flips: dict[str, list[str]] = {}
    for gate in GATES:
        ok = 0
        for cell in STRUCTURAL:
            scan = scan_a if cell.fact == "a" else scan_b
            good = decide(scan, cell, gate) == cell.expect
            ok += good
            if not good:
                flips.setdefault(gate, []).append(cell.id)
        out[gate] = ok
    score_structural.last_flips = flips  # type: ignore[attr-defined]
    return out


def main() -> None:
    rng = np.random.default_rng(757_2)
    print(f"# DAT-757 adversarial round — mixed gate FROZEN, {len(STRUCTURAL)} structural cells\n")

    # ---- A: seed sweep ----
    print("## A — seed sweep (n=20000/12000, 5 fresh seeds)")
    for seed in (11, 22, 33, 44, 55):
        s = score_structural(seed, N, 12_000)
        flips = score_structural.last_flips.get("mixed", [])  # type: ignore[attr-defined]
        print(f"  seed {seed:>3}: eng {s['eng']}/32  row {s['row']}/32  "
              f"row+rfi {s['row+rfi']}/32  mixed {s['mixed']}/32"
              f"{'   mixed misses: ' + ', '.join(flips) if flips else ''}")

    # ---- B: n sweep ----
    print("\n## B — n sweep (seed 77; fact_b scaled n*0.6)")
    for n in (500, 2000, 20_000):
        s = score_structural(77, n, max(300, int(n * 0.6)))
        flips = score_structural.last_flips.get("mixed", [])  # type: ignore[attr-defined]
        print(f"  n={n:>6}: eng {s['eng']}/32  row {s['row']}/32  "
              f"row+rfi {s['row+rfi']}/32  mixed {s['mixed']}/32"
              f"{'   mixed misses: ' + ', '.join(flips) if flips else ''}")

    # ---- C: true-FD determinant-cardinality sweep (the greediness boundary) ----
    # RFI's chance purity depends on BOTH cards: fine determinant (small groups) AND a
    # coarse dependent push perm-FI up. Sweep dep in {24, 4} — dep(4) is the worst case
    # (a fine determinant over a coarse flag-like level).
    print("\n## C — TRUE FD det(card c) -> dep(k): where does mixed's RFI kill a real FD?")
    print(f"  {'card':>6} {'dep_k':>6} {'grp~':>5} {'RFI':>7}  eng  row  mixed")
    n = 20_000
    sweep = [(c, 24) for c in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85)]
    sweep += [(c, 4) for c in (0.3, 0.5, 0.7, 0.8, 0.85)]
    for c, dep_k in sweep:
        k = int(c * n)
        det = rng.permutation(np.arange(n) % k)
        dep = det * dep_k // k  # exact FD det -> dep, dep_k coarse values
        df = pl.DataFrame({"det": det, "dep": dep})
        scan = scan_pairs(df, ["det", "dep"])
        r = rfi_of(scan, "det", "dep")
        marks = {g: edge_decision(scan, "det", "dep", g) for g in ("eng", "row", "mixed")}
        print(f"  {c:>6.2f} {dep_k:>6} {n / k:>5.1f} {r:>7.3f}  "
              f"{'ok' if marks['eng'] else 'XX':>3}  {'ok' if marks['row'] else 'XX':>3}  "
              f"{'ok' if marks['mixed'] else 'XX':>4}")

    # ---- D: dirt sweep on a TRUE FD (the under-built A4 axis) ----
    print("\n## D — TRUE FD city(600)->state(24), f% corrupted rows (SCD dirt)")
    print(f"  {'dirt':>6} {'g3_eng':>8} {'g3_row':>8}  eng  row  mixed   (expect: keep the FD)")
    for f in (0.005, 0.01, 0.02, 0.05):
        city = rng.integers(0, 600, n)
        state = city // 25
        bad = rng.choice(n, int(f * n), replace=False)
        state[bad] = (state[bad] + 1 + rng.integers(0, 22, len(bad))) % 24
        df = pl.DataFrame({"city": city, "state": state})
        scan = scan_pairs(df, ["city", "state"])
        ps = scan.stats[("city", "state")]
        marks = {g: edge_decision(scan, "city", "state", g) for g in ("eng", "row", "mixed")}
        print(f"  {f:>6.1%} {ps.g3_eng_fwd:>8.4f} {ps.g3_row_fwd:>8.4f}  "
              f"{'ok' if marks['eng'] else 'XX':>3}  {'ok' if marks['row'] else 'XX':>3}  "
              f"{'ok' if marks['mixed'] else 'XX':>4}")

    # ---- E: skewed-dependent GRID — determinant shape x skew x dep-card ----
    # Closes the single-point demo: worst-case RFI margin over independent pairs (FP
    # side) and best-case over true controls (FN side), across determinant shapes.
    print("\n## E — skew grid: independent determinants vs skewed deps (expect: reject all)")

    def make_det(shape: str) -> np.ndarray:
        card, tail = shape.split("/")
        c = float(card)
        if tail == "uni":
            return rng.permutation(np.arange(n) % int(c * n))
        n_bulk = 10 if tail == "heavy10" else 3
        det = np.arange(n)  # unique base
        frac = 1.0 - c + n_bulk / n  # tail fraction that lands on bulk codes
        idx = rng.choice(n, int(frac * n), replace=False)
        det[idx] = -rng.integers(1, n_bulk + 1, len(idx))
        return det

    shapes = ["0.10/uni", "0.30/uni", "0.30/heavy3", "0.65/heavy10", "0.85/heavy10"]
    worst_fp_rfi, fp_fail = -1.0, 0
    best_fn_rfi, fn_fail = 2.0, 0
    n_cells = 0
    for p_min in (0.05, 0.01, 0.005, 0.001):
        for dep_k in (2, 5):
            # skewed dep: dominant value, (dep_k-1) minorities sharing p_min
            u = rng.random(n)
            dep = np.where(u < p_min, 1 + (rng.integers(0, dep_k - 1, n)), 0)
            cols: dict[str, np.ndarray] = {f"det{i}": make_det(s) for i, s in enumerate(shapes)}
            true_det = rng.permutation(np.arange(n) % 600)
            cols["true_det"] = true_det
            cols["dep"] = dep
            cols["true_dep"] = np.where(true_det < 600 * p_min, 1, 0)  # same skew, exact FD
            scan = scan_pairs(pl.DataFrame(cols), list(cols))
            for i, s in enumerate(shapes):
                n_cells += 1
                r = rfi_of(scan, f"det{i}", "dep")
                worst_fp_rfi = max(worst_fp_rfi, r)
                if edge_decision(scan, f"det{i}", "dep", "mixed"):
                    fp_fail += 1
                    print(f"    FP: det {s} -> dep(k={dep_k}, min={p_min:.1%}) RFI={r:.3f}")
            r_true = rfi_of(scan, "true_det", "true_dep")
            best_fn_rfi = min(best_fn_rfi, r_true)
            if not edge_decision(scan, "true_det", "true_dep", "mixed"):
                fn_fail += 1
                print(f"    FN: TRUE control lost at k={dep_k}, min={p_min:.1%} RFI={r_true:.3f}")
    print(f"  {n_cells} independent cells x mixed: {fp_fail} FP  "
          f"(worst indep RFI {worst_fp_rfi:+.3f} vs threshold 0.05)")
    print(f"  {4 * 2} true controls  x mixed: {fn_fail} FN  (weakest true RFI {best_fn_rfi:.3f})")

    # ---- F: chaining GRID — length sweep + the distinct-pair merge boundary ----
    print("\n## F1 — chain length: k near-copies, 5 dirty rows per link. Full merge? endpoint drift?")
    base = rng.integers(0, 600, n)
    for k in (3, 5, 8, 10):
        cols_f: dict[str, np.ndarray] = {"c0": base}
        for i in range(1, k):
            nxt = cols_f[f"c{i - 1}"].copy()
            nxt[rng.choice(n, 5, replace=False)] = rng.integers(600 * i, 600 * i + 600, 5)
            cols_f[f"c{i}"] = nxt
        scan = scan_pairs(pl.DataFrame(cols_f), list(cols_f))
        adjacent_ok = all(
            alias_decision(scan, f"c{i}", f"c{i + 1}", "mixed") for i in range(k - 1)
        )
        ps = scan.stats[("c0", f"c{k - 1}")]
        end_g3 = max(ps.g3_eng_fwd, ps.g3_eng_bwd)
        end_direct = alias_decision(scan, "c0", f"c{k - 1}", "mixed")
        print(f"  k={k:>2}: all adjacent merge: {adjacent_ok}  -> union-find merges ALL; "
              f"endpoint pair-g3 {end_g3:.4f} (direct merge would be {end_direct})")

    print("\n## F2 — merge boundary in DISTINCT-PAIR space: Y = X except d disagreeing rows")
    print("   (pair-count alias tolerance = extra distinct pairs <= 1% of d_x — value near-identity;")
    print("    correlation below that NEVER bridges, however strong)")
    x = rng.integers(0, 600, n)
    for d_rows in (2, 4, 6, 10, 20, 100, 1000):
        y = x.copy()
        y[rng.choice(n, d_rows, replace=False)] = rng.integers(600, 1200, d_rows)
        scan = scan_pairs(pl.DataFrame({"x": x, "y": y}), ["x", "y"])
        ps = scan.stats[("x", "y")]
        merged = alias_decision(scan, "x", "y", "mixed")
        print(f"  {d_rows:>5} dirty rows: pair-g3 {max(ps.g3_eng_fwd, ps.g3_eng_bwd):.4f} "
              f"-> {'MERGE' if merged else 'no merge'}")


if __name__ == "__main__":
    main()
