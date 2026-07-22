"""Driver-ordering recall vs entropy_map (DAT-688). Tier-3 (docker + Temporal; llm).

The driver-discovery phase (DAT-546, ``dataraum.analysis.drivers``) ranks a categorical
dimension by the permutation-gated between-group variance reduction of each
``semantic_role='measure'`` column, and reports every group's interesting-slice effect
(``group_mean / baseline − 1``). ``detection-driver-v1`` injects a KNOWN driver:
``inject_driver_effect`` scales ``journal_lines.debit`` by an ascending factor ladder
across cost_center values (the /ground gate PASSED, DAT-688 — a one-sided scale shifts a
group's mean so the variance-reduction statistic reads it; a BALANCED scale is invisible,
the slice_variance wall). One cost_center is left at its natural scale as the in-run
reference.

This oracle grades the persisted ranking against that ground truth by ORDERING, never a
point threshold (ADR-0009 eval grammar):

* the scaled dimension is a SIGNIFICANT driver of the scaled measure under injection
  (∈ ``ranked_dimensions``) and measurably more so than on clean data — the recall
  separation (``test_driver_dimension_recall_vs_clean``);
* the interesting-slice effects for that dimension order by the recorded factor
  (stronger factor → sharper slice), the untouched reference lowest — monotonicity in
  severity (``test_driver_slice_effects_order_by_factor``).

Row-grain / ICC-safe by construction: cost_center is not an entity key (η²≈0 on clean),
so the primary family's exchangeable grain must be ``"row"`` (DAT-544).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from calibration import cube
from calibration import runner as runner_mod
from calibration.metadata_truth import read_driver_rankings
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model")

_INJECTED = "detection-driver-v1"
_CLEAN = "clean"

# KNOWN UPSTREAM GAP (Tier-3 run 2026-07-14, DAT-688). The driver phase's candidate
# dimensions come ENTIRELY from the slicing phase (`_candidate_dims` reads
# SliceDefinition), and slicing currently evaluates only REFERENTIAL (FK-joined)
# dimensions — e.g. journal_lines gets `account_id__account_type`/`account_id__name`
# but never its own FOLDED native column `cost_center`. So the injected driver
# (cost_center × factor) never enters the candidate set and the ranking is empty
# (n_rows=0, "too few candidates"). Verified: the driver phase itself works (clean
# journal_lines.debit ranks account_id drivers; bank_transactions ranks `reconciled`)
# and cost_center scales exactly as designed in the raw data — the sole blocker is
# folded dims not being sliceable, fixed in parallel (folded-dimension slicing). These
# stay xfail(strict=False) so they RUN every calibration and XPASS the moment the fix
# lands — the signal to drop this marker and assert hard.
_FOLDED_DIM_XFAIL = (
    "folded (native) dimensions like cost_center are not yet slice candidates — only "
    "referential FK-joined dims are — so the injected driver never enters the driver "
    "candidate set (DAT-688 Tier-3 finding 2026-07-14; folded-dimension slicing fix pending). "
    "XPASS = the fix landed → remove this marker and assert hard."
)
# Recall separation floor for the dimension's gain (injected vs clean). A FLOOR, not a
# tuned point: the injection scales four cost_centers, so its between-group gain is large
# while clean cost_center gain is ≈0 (the /ground finding) — any positive margin holds.
_GAIN_MARGIN = 0.005

EVAL_ROOT = Path(__file__).parent.parent


def _activate_or_skip(strategy: str) -> None:
    if not runner_mod.sidecar_path(strategy).exists():
        pytest.skip(
            f"no completed run for {strategy!r}; run "
            f"`python -m calibration.run -s {_CLEAN},{_INJECTED}` first"
        )


def _driver_effect_truth(strategy: str) -> dict[str, Any]:
    """The ``(table, measure, dimension, {value: factor})`` the injected run recorded."""
    path = EVAL_ROOT / "data" / strategy / "entropy_map.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    recs = [
        i
        for i in (data.get("injections") or [])
        if (i.get("parameters") or {}).get("family") == "driver_effect"
    ]
    if not recs:
        return {}
    tables = {r["target_file"].replace(".csv", "") for r in recs}
    measures = {r["parameters"]["measure"] for r in recs}
    dims = {r["parameters"]["dimension"] for r in recs}
    assert len(tables) == len(measures) == len(dims) == 1, (
        "driver_effect ground truth must be one (table, measure, dimension)"
    )
    return {
        "table": next(iter(tables)),
        "measure": next(iter(measures)),
        "dimension": next(iter(dims)),
        "by_value": {r["parameters"]["value"]: r["parameters"]["factor"] for r in recs},
    }


def _rankings(strategy: str) -> dict[str, dict[str, Any]]:
    """Materialize this strategy's driver rankings (activates its workspace first)."""
    runner_mod.activate_workspace(strategy)
    with workspace_session() as session:
        return read_driver_rankings(session)


def _dim_gain(ranking: dict[str, Any], dimension: str) -> float:
    for dim, gain in ranking.get("ranked_dimensions", []):
        if dim == dimension:
            return float(gain)
    return 0.0


@pytest.mark.llm
@pytest.mark.xfail(strict=False, reason=_FOLDED_DIM_XFAIL)
def test_driver_dimension_recall_vs_clean(strategy_name: str) -> None:
    """The scaled dimension is a significant driver under injection and above clean."""
    if strategy_name != _INJECTED:
        pytest.skip(f"cross-strategy driver oracle — runs on the {_INJECTED!r} pass only (DAT-797)")
    truth = _driver_effect_truth(_INJECTED)
    assert truth, f"{_INJECTED} recorded no driver_effect ground truth"
    _activate_or_skip(_CLEAN)
    _activate_or_skip(_INJECTED)
    key = f"{truth['table']}.{truth['measure']}"
    dim = truth["dimension"]

    clean = _rankings(_CLEAN)  # materialized before switching workspaces
    injected = _rankings(_INJECTED)
    assert key in injected, (
        f"no driver ranking for {key} in {_INJECTED} — the scaled measure was not "
        f"ranked (measures ranked: {sorted(injected)})"
    )
    inj = injected[key]

    assert inj["grain"] == "row", (
        f"{key}: expected row-grain inference (cost_center is not an entity key — "
        f"ICC-safe by construction, DAT-544), got grain={inj['grain']!r}"
    )

    g_inj = _dim_gain(inj, dim)
    g_clean = _dim_gain(clean.get(key, {}), dim)
    dims_inj = {d for d, _ in inj["ranked_dimensions"]}
    print(
        f"\n[driver recall] {key} dim={dim}: gain injected={g_inj:.4f} clean={g_clean:.4f}; "
        f"ranked_dimensions(injected)={sorted(dims_inj)}"
    )
    assert dim in dims_inj, (
        f"{dim} is not a significant driver of {key} under injection "
        f"(ranked_dimensions={sorted(dims_inj)}) — the injected driver was missed"
    )
    assert g_inj > g_clean + _GAIN_MARGIN, (
        f"{dim} gain not measurably above clean: injected={g_inj:.4f} clean={g_clean:.4f} "
        f"(margin={_GAIN_MARGIN})"
    )


@pytest.mark.llm
@pytest.mark.xfail(strict=False, reason=_FOLDED_DIM_XFAIL)
def test_driver_slice_effects_order_by_factor(strategy_name: str) -> None:
    """Interesting-slice effects for the scaled dimension order by the recorded factor."""
    if strategy_name != _INJECTED:
        pytest.skip(f"cross-strategy driver oracle — runs on the {_INJECTED!r} pass only (DAT-797)")
    truth = _driver_effect_truth(_INJECTED)
    assert truth, f"{_INJECTED} recorded no driver_effect ground truth"
    _activate_or_skip(_INJECTED)
    key = f"{truth['table']}.{truth['measure']}"
    dim = truth["dimension"]
    by_value: dict[str, float] = truth["by_value"]

    inj = _rankings(_INJECTED).get(key, {})
    assert inj, f"no driver ranking for {key} in {_INJECTED}"

    # value → effect for THIS dimension's interesting slices (sharp deviations).
    effect = {
        s["value"]: float(s["effect"])
        for s in inj["interesting_slices"]
        if s["dimension"] == dim
    }
    print(f"\n[driver slices] {key} dim={dim}:")
    for value, eff in sorted(effect.items(), key=lambda kv: kv[1]):
        factor = by_value.get(value)
        tag = f"factor={factor}" if factor is not None else "reference (unscaled)"
        print(f"  {value}: effect={eff:+.4f}  [{tag}]")

    present = [(by_value[v], effect[v]) for v in by_value if v in effect]
    assert len(present) >= 2, (
        f"fewer than two injected {dim} values surfaced as interesting slices "
        f"(surfaced: {sorted(effect)}) — cannot grade ordering"
    )
    # The untouched reference (factor 1.0) must sit lowest — fold it into the ladder.
    reference = [v for v in effect if v not in by_value]
    ladder = sorted(present + [(1.0, effect[v]) for v in reference], key=lambda fe: fe[0])
    effects = [eff for _factor, eff in ladder]
    assert effects == sorted(effects), (
        f"interesting-slice effects for {dim} are not monotone in factor: "
        f"{[(round(f, 2), round(e, 4)) for f, e in ladder]}"
    )
    # The strongest factor is the sharpest slice.
    top_value = max(by_value, key=lambda v: by_value[v])
    assert top_value in effect and effect[top_value] == max(effect.values()), (
        f"the top-factor {dim} value {top_value!r} (factor={by_value[top_value]}) is not "
        f"the sharpest slice (effects={ {k: round(v, 4) for k, v in effect.items()} })"
    )
