"""Shared FD measures + a faithful port of the engine's g3 pipeline (DAT-757 matrix).

Measures (all vectorized, ms-scale at n=20k):
  * engine g3   — 1 - d_a/d_ab, the distinct-count ratio (hierarchies/processor.py:84),
                  computed in DuckDB so NULL semantics match the engine exactly
                  (per-column COUNT(DISTINCT) ignores NULL; the row-literal joint counts
                  (a, NULL) as a present pair).
  * row g3      — classic Kivinen–Mannila: min fraction of rows to delete for the FD to
                  hold exactly. NULL treated as a category (noted; the engine is blind).
  * FI / RFI    — fraction of information and its permutation chance-correction
                  (Mandros–Boley–Vreeken; the Parciak-2024 reliable ranking).

Pipeline port (verbatim logic from analysis/hierarchies/processor.py):
  eligible (constant drop) -> alias union-find (bidirectional g3<=0.01, NO near-key
  guard — the unguarded path) -> directed edges (g3<=0.01, d_a>d_b, determinant guards)
  -> transitive reduction -> maximal chains. Parameterized by a `gate` selecting which
  measure feeds the decisions, so the same pipeline runs as:
    eng      — the engine today (distinct-ratio g3)
    row      — classic row-based g3 swapped in, guards unchanged
    row+rfi  — row g3 AND RFI>RFI_MIN required for every edge and alias union
    mixed    — the matrix-derived recommendation: EDGES row-g3+RFI (dirty-FD
               tolerance, heavy-tail rejection); ALIASES pair-count g3+RFI
               (pair-counting is the conservative semantics for near-duplicate
               role columns; RFI kills independent-full-key merges)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import numpy as np
import polars as pl

# engine constants (hierarchies/processor.py)
FD_MAX_G3 = 0.01
MIN_DISTINCT_DIMENSION = 2
MIN_DISTINCT_DETERMINANT = 3
NEAR_KEY_FRAC = 0.9

RFI_MIN = 0.05
N_PERMS = 40
_PERM_RNG = np.random.default_rng(20260714)


# --------------------------------------------------------------------------- #
# pairwise stats                                                               #
# --------------------------------------------------------------------------- #
@dataclass
class PairStats:
    """All measures for one unordered column pair (a, b)."""

    d_a: int
    d_b: int
    d_ab_engine: int  # DuckDB row-literal joint distinct (engine NULL semantics)
    g3_eng_fwd: float  # a -> b
    g3_eng_bwd: float  # b -> a
    g3_row_fwd: float
    g3_row_bwd: float
    fi_fwd: float
    fi_bwd: float
    _rfi_fwd: float | None = field(default=None, repr=False)
    _rfi_bwd: float | None = field(default=None, repr=False)
    _p_fwd: float | None = field(default=None, repr=False)
    _p_bwd: float | None = field(default=None, repr=False)


def codes_of(s: pl.Series) -> np.ndarray:
    """Integer codes, NULL -> its own category (for row-g3 / FI / RFI)."""
    return s.cast(pl.Utf8).fill_null("␀").rank("dense").cast(pl.Int64).to_numpy() - 1


def _grouped_sorted(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(pair_counts, a_of_pair, boundaries of a-groups) over the (a,b) contingency."""
    packed = a.astype(np.int64) * (b.max() + 1) + b
    uniq, counts = np.unique(packed, return_counts=True)
    a_of_pair = uniq // (b.max() + 1)
    # a_of_pair is sorted (packed sort order groups by a); group boundaries:
    bounds = np.flatnonzero(np.diff(a_of_pair)) + 1
    return counts, a_of_pair, bounds


def _row_g3(a: np.ndarray, b: np.ndarray) -> float:
    """Classic g3(a->b): 1 - (sum over a-groups of the majority-b count)/n."""
    counts, _, bounds = _grouped_sorted(a, b)
    kept = np.maximum.reduceat(counts, np.r_[0, bounds])
    return 1.0 - kept.sum() / len(a)


def _entropy_from_counts(counts: np.ndarray) -> float:
    p = counts / counts.sum()
    return float(-(p * np.log(p)).sum())


def _fi(a: np.ndarray, b: np.ndarray) -> float:
    """FI(a->b) = 1 - H(b|a)/H(b) in [0,1]."""
    _, b_counts = np.unique(b, return_counts=True)
    h_b = _entropy_from_counts(b_counts)
    if h_b == 0.0:
        return 0.0
    counts, _, bounds = _grouped_sorted(a, b)
    n = len(a)
    group_tot = np.add.reduceat(counts, np.r_[0, bounds])
    # H(b|a) = sum_g (n_g/n) * H(counts within group g)
    with np.errstate(divide="ignore", invalid="ignore"):
        # per-pair p log p within its group
        rep = np.repeat(group_tot, np.diff(np.r_[0, bounds, len(counts)]))
        p = counts / rep
        plogp = p * np.log(p)
    h_b_given_a = float(-(np.add.reduceat(plogp, np.r_[0, bounds]) * group_tot / n).sum())
    return 1.0 - h_b_given_a / h_b


def rfi(a: np.ndarray, b: np.ndarray, reps: int = N_PERMS) -> float:
    """RFI(a->b) = FI - E_perm[FI(a, shuffled b)] (chance-corrected reliability)."""
    base = _fi(a, b)
    bc = b.copy()
    perm = np.empty(reps)
    for r in range(reps):
        _PERM_RNG.shuffle(bc)
        perm[r] = _fi(a, bc)
    return base - float(perm.mean())


@dataclass
class Scan:
    """One scanned table: everything the gates need, self-contained per fact."""

    n: int
    singles: dict[str, int]
    stats: dict[tuple[str, str], PairStats]
    codes: dict[str, np.ndarray]


def scan_pairs(df: pl.DataFrame, cols: list[str]) -> Scan:
    """One engine-style DuckDB scan + vectorized row/FI stats for every pair (a < b in
    `cols` order). RFI is computed lazily (see `rfi_of`) — only pairs that pass a
    row-g3 gate ever need it."""
    con = duckdb.connect()
    con.register("t", df)
    parts = ["COUNT(*) AS n"]
    parts += [f'COUNT(DISTINCT "{c}") AS d{i}' for i, c in enumerate(cols)]
    pair_idx: list[tuple[int, int]] = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pair_idx.append((i, j))
            parts.append(f'COUNT(DISTINCT ("{cols[i]}", "{cols[j]}")) AS j_{i}_{j}')
    row = con.execute(f'SELECT {", ".join(parts)} FROM t').fetchone()
    assert row is not None
    n = int(row[0])
    singles = {c: int(row[1 + i]) for i, c in enumerate(cols)}
    joints = {pair_idx[k]: int(row[1 + len(cols) + k]) for k in range(len(pair_idx))}

    codes = {c: codes_of(df.get_column(c)) for c in cols}
    stats: dict[tuple[str, str], PairStats] = {}
    for i, j in pair_idx:
        a, b = cols[i], cols[j]
        d_a, d_b, d_ab = singles[a], singles[b], joints[(i, j)]
        stats[(a, b)] = PairStats(
            d_a=d_a,
            d_b=d_b,
            d_ab_engine=d_ab,
            g3_eng_fwd=1.0 if d_ab == 0 else 1.0 - d_a / d_ab,
            g3_eng_bwd=1.0 if d_ab == 0 else 1.0 - d_b / d_ab,
            g3_row_fwd=_row_g3(codes[a], codes[b]),
            g3_row_bwd=_row_g3(codes[b], codes[a]),
            fi_fwd=_fi(codes[a], codes[b]),
            fi_bwd=_fi(codes[b], codes[a]),
        )
    return Scan(n=n, singles=singles, stats=stats, codes=codes)


PERM_REPS = 2999  # p_min = 1/3000 — resolvable under BH even for a single hit at m~100


def perm_pvalue(scan: Scan, a: str, b: str, reps: int = PERM_REPS) -> float:
    """P_perm(FI(a, shuffled b) >= FI_obs), add-one corrected, cached, directional.

    The variance-honest replacement for RFI's mean-centering: asks where the observed
    dependence sits in the null DISTRIBUTION. Early-stops in 100-perm blocks once the
    exceedance count is high enough that no BH threshold (q<=0.05) could ever reject.
    """
    key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
    ps = scan.stats[key]
    attr = "_p_fwd" if fwd else "_p_bwd"
    cached = getattr(ps, attr)
    if cached is not None:
        return cached
    obs = _fi(scan.codes[a], scan.codes[b])
    bc = scan.codes[b].copy()
    count = done = 0
    while done < reps:
        block = min(100, reps - done)
        for _ in range(block):
            _PERM_RNG.shuffle(bc)
            if _fi(scan.codes[a], bc) >= obs:
                count += 1
        done += block
        if count >= 20:  # p >= 20/reps ~ 0.007..0.1 by now; conservative early exit
            break
    p = (1 + count) / (1 + done)
    setattr(ps, attr, p)
    return p


def bh_reject(pvals: dict, m_family: int, q: float = 0.05) -> set:
    """Benjamini–Hochberg over a family of size ``m_family`` (untested members carry
    p=1 implicitly). Returns the keys whose hypotheses are rejected (significant)."""
    ranked = sorted(pvals.items(), key=lambda kv: kv[1])
    cut = 0
    for k, (_, p) in enumerate(ranked, start=1):
        if p <= q * k / m_family:
            cut = k
    return {key for key, _ in ranked[:cut]}


def rfi_of(scan: Scan, a: str, b: str) -> float:
    """Directional RFI(a->b), cached on the PairStats (lazy — permutations cost)."""
    key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
    ps = scan.stats[key]
    attr = "_rfi_fwd" if fwd else "_rfi_bwd"
    cached = getattr(ps, attr)
    if cached is None:
        cached = rfi(scan.codes[a], scan.codes[b])
        setattr(ps, attr, cached)
    return cached


# --------------------------------------------------------------------------- #
# pair-level decisions per gate                                                #
# --------------------------------------------------------------------------- #
def edge_decision(scan: Scan, a: str, b: str, gate: str) -> bool:
    """Would `gate` assert the directed FD edge a -> b (engine guard set)?"""
    key, fwd = ((a, b), True) if (a, b) in scan.stats else ((b, a), False)
    ps = scan.stats[key]
    d_a, d_b = (ps.d_a, ps.d_b) if fwd else (ps.d_b, ps.d_a)
    if gate == "eng":
        g3 = ps.g3_eng_fwd if fwd else ps.g3_eng_bwd
    else:  # row / row+rfi / mixed all use row-g3 for edges
        g3 = ps.g3_row_fwd if fwd else ps.g3_row_bwd
    if g3 > FD_MAX_G3:
        return False
    if not d_a > d_b:
        return False
    if d_a < MIN_DISTINCT_DETERMINANT or (scan.n and d_a >= NEAR_KEY_FRAC * scan.n):
        return False
    if d_b < MIN_DISTINCT_DIMENSION:  # constant dependent never reaches the edge stage
        return False
    return gate not in ("row+rfi", "mixed") or rfi_of(scan, a, b) > RFI_MIN


def alias_decision(scan: Scan, a: str, b: str, gate: str) -> bool:
    """Would `gate` alias-union a <-> b? Engine path: NO near-key guard (only constants
    are pre-dropped) — ported faithfully; row+rfi additionally requires RFI both ways."""
    key = (a, b) if (a, b) in scan.stats else (b, a)
    ps = scan.stats[key]
    if ps.d_a < MIN_DISTINCT_DIMENSION or ps.d_b < MIN_DISTINCT_DIMENSION:
        return False
    fwd, bwd = (
        (ps.g3_eng_fwd, ps.g3_eng_bwd)
        if gate in ("eng", "mixed")  # mixed keeps PAIR-COUNT semantics for aliases
        else (ps.g3_row_fwd, ps.g3_row_bwd)
    )
    if not (fwd <= FD_MAX_G3 and bwd <= FD_MAX_G3):
        return False
    return gate not in ("row+rfi", "mixed") or (
        rfi_of(scan, a, b) > RFI_MIN and rfi_of(scan, b, a) > RFI_MIN
    )


# --------------------------------------------------------------------------- #
# the assembled pipeline (alias -> edges -> reduction -> chains)               #
# --------------------------------------------------------------------------- #
def _transitive_reduction(edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    succ: dict[str, set[str]] = {}
    for a, b in edges:
        succ.setdefault(a, set()).add(b)

    def reaches(start: str, target: str, skip: tuple[str, str]) -> bool:
        stack, seen = [start], {start}
        while stack:
            node = stack.pop()
            for nxt in succ.get(node, ()):
                if (node, nxt) == skip:
                    continue
                if nxt == target:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    return {(a, b) for (a, b) in edges if not reaches(a, b, skip=(a, b))}


def _maximal_chains(edges: set[tuple[str, str]]) -> list[list[str]]:
    succ: dict[str, list[str]] = {}
    has_incoming: set[str] = set()
    for a, b in sorted(edges):
        succ.setdefault(a, []).append(b)
        has_incoming.add(b)
    starts = sorted({a for a, _ in edges} - has_incoming)
    chains: list[list[str]] = []

    def walk(path: list[str]) -> None:
        nexts = succ.get(path[-1])
        if not nexts:
            if len(path) >= 2:
                chains.append(path)
            return
        for nxt in nexts:
            walk([*path, nxt])

    for start in starts:
        walk([start])
    return chains


@dataclass
class PipelineResult:
    """What one gate's assembled pipeline produced over a candidate set."""

    alias_groups: list[list[str]]
    rep: dict[str, str]
    chains: list[list[str]]


def assemble(scan: Scan, cols: list[str], gate: str) -> PipelineResult:
    """Faithful processor.py flow (alias -> edges -> reduction -> chains) under `gate`."""
    eligible = [c for c in cols if scan.singles[c] >= MIN_DISTINCT_DIMENSION]

    # alias union-find (the unguarded path)
    parent = {c: c for c in eligible}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(eligible):
        for b in eligible[i + 1 :]:
            if alias_decision(scan, a, b, gate):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[min(ra, rb)] = max(ra, rb)

    members: dict[str, list[str]] = {}
    for c in eligible:
        members.setdefault(find(c), []).append(c)
    groups = [sorted(g) for g in members.values() if len(g) >= 2]
    rep = {c: sorted(g)[0] for g in members.values() for c in g}

    # directed edges on collapsed reps
    edges: set[tuple[str, str]] = set()
    for i, a in enumerate(eligible):
        for b in eligible[i + 1 :]:
            ra, rb = rep[a], rep[b]
            if ra == rb:
                continue
            if edge_decision(scan, a, b, gate):
                edges.add((ra, rb))
            elif edge_decision(scan, b, a, gate):
                edges.add((rb, ra))

    chains = _maximal_chains(_transitive_reduction(edges))
    return PipelineResult(alias_groups=groups, rep=rep, chains=chains)
