"""Tier-1: the DAT-544 driver-gate exchangeability verdict, pinned against the engine.

The driver-discovery gate (analysis/drivers) ranks dimensions by a within-dataset
permutation null. That null shuffles the measure ACROSS ROWS, which is only valid when
rows are exchangeable under H0 — FALSE for repeated-entity data with a measure that
clusters within entity (account balance by account, ...). The DAT-544 probe found the
row-wise null inflates entity-level-null FDR to ~100% on clustered data; the fix line
DAT-552 (ICC switch) -> DAT-561 (per-candidate grain routing) -> DAT-563 (N-entity
home-grain routing) closes it. This file is that verdict's executable form, run against
the REAL engine functions so it cannot silently rot.

Deterministic (fixed seeds + the engine's seeded RNG) — the bounds are margins around
reproducible counts, the kill-gate criterion, not tuned points. n_perm is reduced for
the dev loop; the separation is stark enough to survive it.

The real non-finance fixture transfer (nycflights13 / OpenML adult) was validated
out-of-rig (2026-06-17/18, recorded on DAT-552/561/563 and in session memory); it needs
external data + 300k rows, so it is not re-run here. The synthetic clustered + crossed
corpora exercise the same exchangeability mechanism in milliseconds.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl
import pytest

drivers = pytest.importorskip("dataraum.analysis.drivers.processor")

from dataraum.analysis.drivers.criterion import (  # noqa: E402
    DEFAULT_MIN_SUPPORT,
    DEFAULT_MISSINGNESS_GATE,
)
from dataraum.analysis.drivers.models import DriverRanking, Measure  # noqa: E402
from dataraum.analysis.drivers.processor import (  # noqa: E402
    DEFAULT_ICC_THRESHOLD,
    DEFAULT_MIN_ENTITIES,
    _home_grain_partition,
    _routed_ranking,
    _row_wise_ranking,
)
from dataraum.analysis.drivers.tree import DEFAULT_ALPHA, DEFAULT_MAX_DEPTH  # noqa: E402

N_PERM = 200          # reduced for the dev loop; the separation survives it
SEEDS = 6
ALPHA = DEFAULT_ALPHA
FDR_BAR = 2 * ALPHA   # the gate's stated FDR target


def _surfaced(ranking: DriverRanking) -> set[str]:
    """Dims that cleared the null in EITHER grain family (primary + secondary)."""
    s = {d for d, _g in ranking.ranked_dimensions}
    for sd in getattr(ranking, "secondary_dimensions", []) or []:
        s.add(sd.dimension)
    return s


def _route(
    frame: pl.DataFrame, dims: list[str], measure: Measure, cluster_keys: list[str], *, seed: int
) -> DriverRanking:
    return _routed_ranking(
        frame, dims, measure, cluster_keys, seed=seed, max_depth=DEFAULT_MAX_DEPTH,
        alpha=ALPHA, min_support=DEFAULT_MIN_SUPPORT, missingness_gate=DEFAULT_MISSINGNESS_GATE,
        n_perm=N_PERM, top_k_slices=5, icc_threshold=DEFAULT_ICC_THRESHOLD,
        min_entities=DEFAULT_MIN_ENTITIES,
    )


def _row_wise(frame: pl.DataFrame, dims: list[str], measure: Measure, *, seed: int) -> DriverRanking:
    return _row_wise_ranking(
        frame, dims, measure, seed=seed, max_depth=DEFAULT_MAX_DEPTH, alpha=ALPHA,
        min_support=DEFAULT_MIN_SUPPORT, missingness_gate=DEFAULT_MISSINGNESS_GATE,
        n_perm=N_PERM, top_k_slices=5,
    )


# ── synthetic corpora (per-entity random effect = the within-entity correlation) ──
def _clustered(rng: np.random.Generator, *, n_ent: int = 120, per: int = 70) -> pl.DataFrame:
    """One entity-level driver + two entity-level nulls + a row-level null; high ICC."""
    ent = np.repeat(np.arange(n_ent), per)
    drv = rng.integers(0, 4, n_ent)
    eff = np.array([-0.6, -0.2, 0.2, 0.6])[drv] + rng.normal(0, 0.7, n_ent)
    y = np.exp(6.0 + eff[ent] + rng.normal(0, 0.5, n_ent * per))
    return pl.DataFrame({
        "entity": ent,
        "measure": y,
        "D_ent": [f"d{g}" for g in drv[ent]],
        "N_ent_K6": [f"a{g}" for g in rng.integers(0, 6, n_ent)[ent]],
        "N_ent_K30": [f"b{g}" for g in rng.integers(0, 30, n_ent)[ent]],
        "N_row_K6": [f"r{g}" for g in rng.integers(0, 6, n_ent * per)],
    })


_CLUSTER_DIMS = ["D_ent", "N_ent_K6", "N_ent_K30", "N_row_K6"]
_ENT_NULLS = ["N_ent_K6", "N_ent_K30"]


def _measure_corpus(rng: np.random.Generator, kind: str, *, n: int = 8000) -> tuple[pl.DataFrame, Measure]:
    dv = rng.integers(0, 4, n)
    cols: dict[str, Any] = {
        "D_e25": [f"v{x}" for x in dv],
        "N_lowcard": [f"l{v}" for v in rng.integers(0, 6, n)],
        "N_midcard": [f"d{v}" for v in rng.integers(0, 60, n)],
    }
    eff = 0.25 * (dv - 1.5) / 1.5
    if kind == "flow":
        cols["measure"] = rng.lognormal(6.0, 1.1, n) * (1.0 + eff)
        return pl.DataFrame(cols), Measure(target_type="flow", column="measure")
    if kind == "stock":
        cols["measure"] = 100_000.0 * (1.0 + eff) * (1.0 + rng.normal(0, 0.08, n))
        return pl.DataFrame(cols), Measure(target_type="stock", column="measure")
    rev = rng.lognormal(6.0, 1.4, n)
    cols["profit"] = rev * (0.30 + 0.10 * (dv - 1.5) / 1.5) + rng.normal(0, 0.05, n) * rev
    cols["revenue"] = rev
    return pl.DataFrame(cols), Measure(target_type="ratio", numerator="profit", denominator="revenue")


def _crossed(rng: np.random.Generator, *, n_cust: int = 120, n_prod: int = 100, n: int = 18_000) -> pl.DataFrame:
    """Crossed customer x product, both clustering; each entity has a driver + a null."""
    cust = rng.integers(0, n_cust, n)
    prod = rng.integers(0, n_prod, n)
    cg = rng.integers(0, 4, n_cust)
    pg = rng.integers(0, 4, n_prod)
    ce = np.array([-0.6, -0.2, 0.2, 0.6])[cg] + rng.normal(0, 0.7, n_cust)
    pe = np.array([-0.6, -0.2, 0.2, 0.6])[pg] + rng.normal(0, 0.7, n_prod)
    y = np.exp(6.0 + ce[cust] + pe[prod] + rng.normal(0, 0.4, n))
    return pl.DataFrame({
        "customer": cust,
        "product": prod,
        "measure": y,
        "D_cust": [f"dc{g}" for g in cg[cust]],
        "D_prod": [f"dp{g}" for g in pg[prod]],
        "N_cust_K30": [f"nc{g}" for g in rng.integers(0, 30, n_cust)[cust]],
        "N_prod_K6": [f"np{g}" for g in rng.integers(0, 6, n_prod)[prod]],
        "N_row_K6": [f"r{g}" for g in rng.integers(0, 6, n)],
    })


def test_rowwise_null_inflates_entity_null_fdr_on_clustered_data() -> None:
    """The bug the routing exists to fix: with NO cluster_key, the row-wise null treats
    20k clustered rows as 20k independent obs and a pure-noise per-entity attribute
    surfaces as a 'driver' almost every seed. (Documents WHY a cluster_key is needed.)"""
    fp = sum(
        any(n in _surfaced(_row_wise(_clustered(np.random.default_rng(s)), _CLUSTER_DIMS,
                                     Measure(target_type="flow", column="measure"), seed=s))
            for n in _ENT_NULLS)
        for s in range(SEEDS)
    )
    assert fp >= SEEDS - 1, f"expected near-universal row-wise inflation, got {fp}/{SEEDS}"


def test_cluster_routing_controls_entity_null_fdr() -> None:
    """With cluster_keys declared, entity-constant nulls take the entity-grain null and
    are gated: FDR <= 2*alpha, while the real entity-level driver still surfaces."""
    meas = Measure(target_type="flow", column="measure")
    fp = drv = 0
    for s in range(SEEDS):
        r = _route(_clustered(np.random.default_rng(s)), _CLUSTER_DIMS, meas, ["entity"], seed=s)
        assert r.grain == "entity" and r.n_rows < 200, "high-ICC measure must use entity grain"
        surf = _surfaced(r)
        fp += sum(n in surf for n in _ENT_NULLS)
        drv += "D_ent" in surf
    assert fp <= math.ceil(FDR_BAR * SEEDS * len(_ENT_NULLS)) + 1, f"entity-null FDR not held: {fp}"
    assert drv >= 1, "the real entity-level driver never surfaced under correct (entity) inference"


@pytest.mark.parametrize("kind", ["flow", "stock", "ratio"])
def test_measure_type_separates_driver_from_nulls(kind: str) -> None:
    """flow / stock / ratio: the +-25% driver surfaces every seed and i.i.d. nulls stay
    gated (FDR <= 2*alpha). Ratio uses the engine's support-weighted target."""
    nulls = ["N_lowcard", "N_midcard"]
    drv = fp = 0
    for s in range(SEEDS):
        df, meas = _measure_corpus(np.random.default_rng(100 + s), kind)
        surf = _surfaced(_row_wise(df, ["D_e25", *nulls], meas, seed=s))
        drv += "D_e25" in surf
        fp += sum(n in surf for n in nulls)
    assert drv == SEEDS, f"{kind}: driver recall {drv}/{SEEDS}"
    assert fp <= math.ceil(FDR_BAR * SEEDS * len(nulls)) + 1, f"{kind}: null FDR not held ({fp})"


def test_multi_cluster_keys_route_to_home_grain() -> None:
    """Crossed customer x product: each candidate homes at the entity it is constant
    within, each entity-level driver surfaces from its own grain family, and every null
    is gated per family — no row-wise leak, no grain mixing (DAT-563)."""
    keys = ["customer", "product"]
    dims = ["D_cust", "N_cust_K30", "D_prod", "N_prod_K6", "N_row_K6"]
    nulls = ["N_cust_K30", "N_prod_K6", "N_row_K6"]
    # partition is structural — assert it once on a representative draw
    home, row = _home_grain_partition(_crossed(np.random.default_rng(0)), keys, dims)
    assert set(home.get("customer", [])) == {"D_cust", "N_cust_K30"}
    assert set(home.get("product", [])) == {"D_prod", "N_prod_K6"}
    assert row == ["N_row_K6"]

    meas = Measure(target_type="flow", column="measure")
    hit = {"D_cust": 0, "D_prod": 0}
    fp = 0
    for s in range(SEEDS):
        surf = _surfaced(_route(_crossed(np.random.default_rng(s)), dims, meas, keys, seed=s))
        for d in hit:
            hit[d] += d in surf
        fp += sum(n in surf for n in nulls)
    assert hit["D_cust"] >= SEEDS - 1 and hit["D_prod"] >= SEEDS - 1, f"driver recall {hit}"
    assert fp <= math.ceil(FDR_BAR * SEEDS * len(nulls)) + 1, f"per-family null FDR not held ({fp})"
