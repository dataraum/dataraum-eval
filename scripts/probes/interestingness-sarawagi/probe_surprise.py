"""Slice-interestingness /ground gate — Sarawagi surprise vs rollup expectation.

CLAIM UNDER TEST (to refute; pre-registered, ONE attempt)
---------------------------------------------------------
"Sarawagi's discovery-driven surprise (VLDB'98) — the standardized residual of a
cell's aggregate against its log-linear main-effects (rollup) expectation —
separates an injected localized slice shift from clean natural variation by a
margin: the injected slice ranks top-5 in ≥ 0.8 of seeds at a 20% shift
(block grain) / 50% shift (single-cell grain), AND the injected surprise clears
the clean-cube max-surprise p95, under heavy-tailed noise."

Named method: Sarawagi, discovery-driven exploration of OLAP cubes — expected
cell value from the log-linear model of lower-order group-bys (main-effects
ANOVA decomposition on log aggregates), surprise = |residual| / robust scale
(MAD). No invented score maps; the statistic is the studentized residual.

Distinct from the DAT-545 driver ranking by construction: drivers rank AXES by
explained variance (permutation importance); this ranks CELLS by deviation from
their rollup expectation. A global row effect (whole region up 30%) must be
ABSORBED by the model (that story belongs to drivers) — leg (d) grades exactly
that discriminant validity.

THE ATTACK
----------
(a) CLEAN, heavy tails: lognormal row noise (sigma 0.8) — fat-tailed cells fake
    surprise; 20 seeds give the natural max-surprise distribution.
(b) INJECTED: one (region, product) BLOCK × (1+δ), δ ∈ {0.1, 0.2, 0.5}, and one
    single (region, product, month) CELL × (1+δ), δ ∈ {0.2, 0.5, 1.0}; rank of
    the injected cell(s) among all 576.
(c) SMALL SUPPORT: one clean cell holds 4 rows (vs ~50) — does its noisy
    aggregate false-fire? (If yes: the boundary is a support floor, reported,
    never a tuned constant.)
(d) GLOBAL ROW EFFECT: whole region × 1.3 — the main-effects model must absorb
    it; no cell of that region may enter the top-5 systematically.

Kill: injected block at δ=0.2 (or cell at δ=0.5) below 0.8 top-5 frequency, or
clean/injected surprise distributions overlap at those δ, or (d) false-fires.

IMPLEMENTATION RECORD (honesty trail)
-------------------------------------
v1 (first run, RECORDED): an unfaithful simplification — finest-grain cells
only, support-blind global MAD. Results: block@20% 7/20, cell@50% 14/20,
small-support FP 8/20, (d) 10/20 ≈ the 49% chance baseline (my printed baseline
formula was wrong; (d) actually passed). Two gaps vs the published method:
Sarawagi scores surprise at EVERY group-by level of the lattice (a block shift
must be graded at its (region, product) margin, where it aggregates 6 cells of
evidence), and standardizes by per-cell variance (support-aware). v2 below =
the published method — same fixtures, same pre-registered thresholds, one
rerun. Still failing → CUT.

Run:  uv run python scripts/probes/interestingness-sarawagi/probe_surprise.py
"""

from __future__ import annotations

import numpy as np

R, P, T = 8, 12, 6  # regions x products x months = 576 cells
ROWS_PER_CELL = 50
SIGMA = 0.8  # lognormal row noise — heavy-tailed by construction
N_SEEDS = 20
TOP_K = 5


def build_cube(rng: np.random.Generator) -> np.ndarray:
    """Cell sums S[r,p,t] of a multiplicative cube with lognormal row noise."""
    a = rng.normal(0, 0.5, R)  # region effects
    b = rng.normal(0, 0.5, P)  # product effects
    c = rng.normal(0, 0.2, T)  # month effects
    mu = 4.0 + a[:, None, None] + b[None, :, None] + c[None, None, :]
    counts = np.full((R, P, T), ROWS_PER_CELL)
    # row-level: sum of ROWS_PER_CELL lognormals per cell (vectorized via moments
    # would hide the tail; draw real rows)
    noise = rng.lognormal(0.0, SIGMA, (R, P, T, ROWS_PER_CELL))
    sums = np.exp(mu)[..., None] * noise
    return sums.sum(axis=-1), counts


def _standardized_residual(log_s: np.ndarray, rel_noise_sd: np.ndarray) -> np.ndarray:
    """|residual| of the log main-effects (ANOVA) fit, variance-aware studentized.

    ``rel_noise_sd`` is each cell's sampling-noise sd relative to the level's
    common support (∝ 1/sqrt(n_cell)) — the published model's variance term:
    a thin cell's residual is divided by its wider expected noise, not judged
    against the common scale.
    """
    grand = log_s.mean()
    expected = np.full_like(log_s, grand)
    for ax in range(log_s.ndim):
        other = tuple(i for i in range(log_s.ndim) if i != ax)
        eff = log_s.mean(axis=other) - grand
        shape = [1] * log_s.ndim
        shape[ax] = -1
        expected = expected + eff.reshape(shape)
    resid = (log_s - expected) / rel_noise_sd
    mad = np.median(np.abs(resid - np.median(resid)))
    scale = 1.4826 * mad if mad > 0 else resid.std() or 1.0
    return np.abs(resid) / scale


def surprise_lattice(
    cells: np.ndarray, counts: np.ndarray
) -> dict[str, np.ndarray]:
    """Sarawagi surprise at every 2-way+ group-by level of the (r, p, t) lattice.

    The finest level scores single cells; each 2-way margin scores the summed
    block — the operator's semantics: a (region, product) shift surfaces at the
    (region, product) level, not as six separate finest-grain whispers.
    """
    base = np.sqrt(counts.mean() / counts)  # relative sampling-noise sd, finest
    out = {"rpt": _standardized_residual(np.log(cells), base)}
    for name, ax in (("rp", 2), ("rt", 1), ("pt", 0)):
        s = cells.sum(axis=ax)
        n = counts.sum(axis=ax)
        out[name] = _standardized_residual(np.log(s), np.sqrt(n.mean() / n))
    return out


def top_k_cells(s: np.ndarray, k: int = TOP_K) -> list[tuple[int, ...]]:
    flat = np.argsort(s, axis=None)[::-1][:k]
    return [tuple(np.unravel_index(i, s.shape)) for i in flat]


def main() -> None:
    print(f"# Sarawagi surprise gate — {R}x{P}x{T} cube, {ROWS_PER_CELL} rows/cell, "
          f"lognormal sigma={SIGMA}, {N_SEEDS} seeds\n")

    # ---- (a) clean: per-level natural max-surprise + top-cell stability ----
    max_clean: dict[str, list[float]] = {"rpt": [], "rp": [], "rt": [], "pt": []}
    top_cells = []
    for seed in range(N_SEEDS):
        cells, counts = build_cube(np.random.default_rng(1000 + seed))
        lat = surprise_lattice(cells, counts)
        for lvl, s in lat.items():
            max_clean[lvl].append(float(s.max()))
        top_cells.append(top_k_cells(lat["rpt"], 1)[0])
    p95 = {lvl: float(np.quantile(v, 0.95)) for lvl, v in max_clean.items()}
    stability = max(top_cells.count(c) for c in set(top_cells)) / N_SEEDS
    print("## (a) clean max-surprise p95 per level: "
          + "  ".join(f"{lvl}={v:.2f}" for lvl, v in p95.items())
          + f"; finest top-cell recurrence {stability:.0%}")

    # ---- (b) injected block + cell (graded at the injection's own grain) ----
    print("\n## (b) injections (block graded at the (r,p) level; cell at finest)")
    for grain, deltas in (("block", (0.1, 0.2, 0.5)), ("cell", (0.2, 0.5, 1.0))):
        for delta in deltas:
            hits, inj_s = 0, []
            for seed in range(N_SEEDS):
                rng = np.random.default_rng(1000 + seed)
                cells, counts = build_cube(rng)
                r0, p0, t0 = seed % R, (seed * 5) % P, (seed * 3) % T
                if grain == "block":
                    cells[r0, p0, :] *= 1 + delta
                else:
                    cells[r0, p0, t0] *= 1 + delta
                lat = surprise_lattice(cells, counts)
                if grain == "block":
                    hits += (r0, p0) in top_k_cells(lat["rp"])
                    inj_s.append(float(lat["rp"][r0, p0]))
                else:
                    hits += (r0, p0, t0) in top_k_cells(lat["rpt"])
                    inj_s.append(float(lat["rpt"][r0, p0, t0]))
            lvl = "rp" if grain == "block" else "rpt"
            med = float(np.median(inj_s))
            print(f"  {grain} +{delta:.0%}: top-5 hit {hits}/{N_SEEDS}  "
                  f"injected surprise p50={med:.2f} "
                  f"(clean {lvl} p95 {p95[lvl]:.2f}) {'CLEAR' if med > p95[lvl] else 'overlap'}")

    # ---- (c) small support: variance-aware studentization must not false-fire ----
    fp = 0
    for seed in range(N_SEEDS):
        rng = np.random.default_rng(2000 + seed)
        cells, counts = build_cube(rng)
        r0, p0, t0 = 2, 3, 1
        few = rng.lognormal(0, SIGMA, 4) * (cells[r0, p0, t0] / ROWS_PER_CELL)
        cells[r0, p0, t0] = few.sum() * (ROWS_PER_CELL / 4)
        counts[r0, p0, t0] = 4
        lat = surprise_lattice(cells, counts)
        fp += (r0, p0, t0) in top_k_cells(lat["rpt"])
    print(f"\n## (c) small-support cell (4 rows, clean): false top-5 {fp}/{N_SEEDS}")

    # ---- (d) global row effect absorbed (drivers' story, not a cell story) ----
    leak = 0
    for seed in range(N_SEEDS):
        cells, counts = build_cube(np.random.default_rng(3000 + seed))
        cells[seed % R, :, :] *= 1.3
        lat = surprise_lattice(cells, counts)
        leak += any(c[0] == seed % R for c in top_k_cells(lat["rpt"]))
    chance = 1 - (1 - P * T / (R * P * T)) ** TOP_K
    print(f"## (d) whole-region x1.3: region cells in finest top-5 {leak}/{N_SEEDS} "
          f"(chance baseline ~{chance:.0%} of seeds)")

    print("\n## VERDICT (pre-registered): BUILD iff block@20% and cell@50% hit >= 16/20")
    print("   with CLEAR margins, small-support FP low, and (d) at chance level; else CUT.")


if __name__ == "__main__":
    main()
