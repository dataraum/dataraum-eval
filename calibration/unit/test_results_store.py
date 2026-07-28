"""Tier-1: the immutable verdict store (DAT-862) — append, filter, diff, and the
four comparability extensions (RFC 5): values, wild rows, the dimension coordinate,
reducer variance."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from calibration import results_store, verdict_values
from calibration.cube import Needs
from calibration.scoreboard import DetectorFireStats, Scoreboard


def _ledger(status_a: str = "passed", status_b: str = "skipped") -> dict[str, dict[str, Any]]:
    return {
        "calibration/test_detector_recall.py::test_x": {"status": status_a},
        "calibration/test_ground_truth.py::test_y": {"status": status_b, "reason": "no data"},
        # Tier-1/2 nodeids must never enter the run record:
        "calibration/unit/test_cube.py::test_z": {"status": "passed"},
    }


def _valued(name: str, value: float, **kw: Any) -> list[dict[str, Any]]:
    return [asdict(verdict_values.make(name, value, **kw))]


def test_record_filters_unit_and_roundtrips(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    n = results_store.record_pass("detection-v1", _ledger(), store=store)
    assert n == 2  # the unit nodeid was filtered

    rows = results_store.load(store=store)
    assert len(rows) == 2
    by_oracle = {r["oracle"]: r for r in rows}
    rec = by_oracle["calibration/test_detector_recall.py::test_x"]
    assert rec["dataset"] == "detection-v1"
    assert rec["vertical"] == "finance"
    assert rec["status"] == "passed"
    assert rec["module"] == "test_detector_recall"
    # cube enrichment: the declared stage + oracle version ride on every row
    assert rec["from_stage"] == "operating_model"
    assert rec["oracle_version"] == 1
    assert rec["engine_commit"] and rec["eval_commit"]
    # durable-identity hint (DAT-736 pin protocol): present, tri-state — never absent
    assert rec["engine_on_main"] in (True, False, None)
    # one pass_id groups the batch
    assert len({r["pass_id"] for r in rows}) == 1


def test_unit_only_pass_writes_nothing(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    n = results_store.record_pass(
        "detection-v1",
        {"calibration/unit/test_cube.py::test_z": {"status": "passed"}},
        store=store,
    )
    assert n == 0
    assert not store.exists()


def test_diff_last_two_is_the_regression_query(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    results_store.record_pass("detection-v1", _ledger("passed", "skipped"), store=store)
    # other-strategy noise must not enter this strategy's history
    results_store.record_pass("clean", _ledger("passed", "passed"), store=store)
    results_store.record_pass("detection-v1", _ledger("failed", "skipped"), store=store)

    diff = results_store.diff_last_two("detection-v1", store=store)
    assert diff["passes"] == 2
    assert diff["changed"] == {
        "calibration/test_detector_recall.py::test_x": ("passed", "failed")
    }
    assert diff["gone"] == [] and diff["new"] == []

    assert len(results_store.passes("clean", store=store)) == 1


def test_diff_needs_two_passes(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    results_store.record_pass("detection-v1", _ledger(), store=store)
    diff = results_store.diff_last_two("detection-v1", store=store)
    assert diff["passes"] == 1 and diff["changed"] == {}


# ---------------------------------------------------------------------------
# ext 1 — the value, and the threshold that judged it
# ---------------------------------------------------------------------------


def test_values_ride_the_row_and_query_back(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    ledger = _ledger()
    ledger["calibration/test_detector_recall.py::test_x"]["values"] = _valued(
        "delta", 0.42, threshold=0.05, comparator=">", unit="margin", subject="a.b:null_ratio"
    )
    results_store.record_pass("detection-v1", ledger, store=store)

    got = results_store.values("detection-v1", name="delta", store=store)
    assert len(got) == 1
    assert got[0]["value"] == 0.42 and got[0]["threshold"] == 0.05
    # the pass coordinates ride along, so a distribution is one query
    assert got[0]["engine_commit"] and got[0]["oracle"].endswith("::test_x")
    assert results_store.values("detection-v1", name="nope", store=store) == []
    assert results_store.values(
        "detection-v1", subject="a.b:null_ratio", store=store
    )[0]["name"] == "delta"


def test_a_red_oracle_keeps_its_value(tmp_path: Path) -> None:
    """The failing margin is the one worth trending — recording never gates."""
    store = tmp_path / "verdicts.jsonl"
    ledger = _ledger(status_a="failed")
    ledger["calibration/test_detector_recall.py::test_x"]["values"] = _valued(
        "delta", 0.01, threshold=0.05, comparator=">"
    )
    results_store.record_pass("detection-v1", ledger, store=store)
    rows = [r for r in results_store.load(store=store) if r["status"] == "failed"]
    assert rows[0]["values"][0]["value"] == 0.01


# ---------------------------------------------------------------------------
# ext 2 — wild rows in the same store, tagged so they can never become a gate
# ---------------------------------------------------------------------------


def _stats(detector_id: str, fire_rate: float) -> DetectorFireStats:
    """A real scoreboard row — the store reads the REAL dataclass's fields, so a
    renamed field breaks this Tier-1 test instead of a wild run's retention."""
    return DetectorFireStats(
        detector_id=detector_id, in_slice=True, status="active",
        n_targets=10, n_measured=8, n_abstained=2, n_fired=4, fire_rate=fire_rate,
        score_min=0.0, score_median=0.1, score_max=0.9, score_mean=0.25,
    )


def _board(*stats: DetectorFireStats) -> Scoreboard:
    return Scoreboard(
        strategy="rel-f1", total_rows=42, per_detector=list(stats),
        mute=["dead_detector"], never_fired=[], saturated=["loud_detector"],
    )


def test_tier_coordinate_separates_wild_from_synthetic(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    results_store.record_pass("detection-v1", _ledger(), store=store)
    results_store.record_pass("rel-f1", _ledger(), store=store)

    by_ds = {r["dataset"]: r for r in results_store.load(store=store)}
    assert by_ds["detection-v1"]["tier"] == "synthetic"
    assert by_ds["detection-v1"]["vertical"] == "finance"
    # rel-f1 is a registered wild corpus (calibration/corpus_registry.yaml)
    assert by_ds["rel-f1"]["tier"] == "wild"
    assert by_ds["rel-f1"]["vertical"] == "rel-f1"


def test_wild_scoreboard_is_retained_but_never_a_verdict(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    board = _board(_stats("loud_detector", 0.95), _stats("quiet_detector", 0.1))
    assert results_store.record_scoreboard("rel-f1", board, store=store) == 2

    # It is retained under the same coordinates...
    rows = results_store.load(store=store)
    assert {r["tier"] for r in rows} == {"wild"}
    assert {r["kind"] for r in rows} == {results_store.KIND_SCOREBOARD}
    assert {r["status"] for r in rows} == {"reported"}

    # ...and is invisible to every verdict query, so a fire rate can never regress.
    assert results_store.passes("rel-f1", store=store) == []
    assert results_store.diff_last_two("rel-f1", store=store)["passes"] == 0

    rates = results_store.fire_rates("rel-f1", store=store)
    assert [r["detector_id"] for r in rates] == ["loud_detector", "quiet_detector"]
    assert rates[0]["observations"][0]["fire_rate"] == 0.95
    assert rates[0]["observations"][0]["flags"] == ["saturated"]


def test_empty_scoreboard_writes_nothing(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    assert results_store.record_scoreboard("rel-f1", _board(), store=store) == 0
    assert not store.exists()


# ---------------------------------------------------------------------------
# ext 3 — the dimension coordinate and the coverage-map honesty gate
# ---------------------------------------------------------------------------


_DIM_REG = {
    "test_detector_recall": Needs(
        vertical="finance", datasets=None, from_stage="operating_model", dimension="demand"
    ),
    "test_ground_truth": Needs(
        vertical="finance", datasets=None, from_stage="raw", dimension="capital"
    ),
}


def _dim_pass(store: Path, *, demand_values: list[dict[str, Any]], capital_status: str) -> None:
    ledger = _ledger(status_a="passed", status_b=capital_status)
    ledger["calibration/test_detector_recall.py::test_x"]["values"] = demand_values
    results_store.record_pass("detection-v1", ledger, store=store, reg=_DIM_REG)


def test_dimension_lit_requires_a_value_that_held(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    _dim_pass(
        store,
        demand_values=_valued("relative_error", 0.4, threshold=1.0, comparator="<="),
        capital_status="skipped",
    )
    assert results_store.dimension_status("detection-v1", store=store) == {
        "demand": "lit",      # graded, judged, held
        "capital": "dark",    # stood down
    }


def test_dimension_out_of_tolerance_is_partial_not_lit(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    _dim_pass(
        store,
        demand_values=_valued("relative_error", 9.0, threshold=1.0, comparator="<="),
        capital_status="passed",
    )
    got = results_store.dimension_status("detection-v1", store=store)
    assert got["demand"] == "partial"
    # graded but with no judged value behind it — grounded-but-ungraded
    assert got["capital"] == "partial"


def test_reported_only_value_never_lights_a_dimension(tmp_path: Path) -> None:
    """The failure the honesty gate exists to prevent: a map that lies."""
    store = tmp_path / "verdicts.jsonl"
    _dim_pass(store, demand_values=_valued("relative_error", 0.4), capital_status="skipped")
    assert results_store.dimension_status("detection-v1", store=store)["demand"] == "partial"


def test_undeclared_dimensions_are_absent_not_dark(tmp_path: Path) -> None:
    """'Nothing claims this' and 'something claims it and failed' are different facts."""
    store = tmp_path / "verdicts.jsonl"
    results_store.record_pass("detection-v1", _ledger(), store=store, reg={})
    assert results_store.dimension_status("detection-v1", store=store) == {}


# ---------------------------------------------------------------------------
# ext 4 — non-determinism reported, never suppressed
# ---------------------------------------------------------------------------


def test_variance_reports_flips_and_spread_at_one_pin(tmp_path: Path) -> None:
    store = tmp_path / "verdicts.jsonl"
    for delta, status in ((0.40, "passed"), (0.20, "failed"), (0.30, "passed")):
        ledger = _ledger(status_a=status)
        ledger["calibration/test_detector_recall.py::test_x"]["values"] = _valued(
            "delta", delta, threshold=0.05, comparator=">", subject="a.b"
        )
        results_store.record_pass("detection-v1", ledger, store=store)

    report = results_store.variance("detection-v1", store=store)
    assert len(report["groups"]) == 1  # one (engine, eval) commit pair
    group = report["groups"][0]
    assert group["repeats"] == 3

    flap = {f["oracle"]: f for f in group["flapping"]}
    assert list(flap) == ["calibration/test_detector_recall.py::test_x"]
    assert flap["calibration/test_detector_recall.py::test_x"]["flip_rate"] == 1.0
    # the working tree decides whether "same pin" is a proof or a hope
    assert group["dirty"] is ("dirty" in group["engine_commit"] + str(group["eval_commit"]))

    spread = {(s["name"], s["subject"]): s for s in group["value_spread"]}
    delta_spread = spread[("delta", "a.b")]
    assert delta_spread["n"] == 3
    assert delta_spread["min"] == 0.20 and delta_spread["max"] == 0.40
    assert delta_spread["stdev"] > 0


def test_variance_needs_repeats(tmp_path: Path) -> None:
    """One pass is not a distribution — nothing to report, and nothing invented."""
    store = tmp_path / "verdicts.jsonl"
    results_store.record_pass("detection-v1", _ledger(), store=store)
    assert results_store.variance("detection-v1", store=store)["groups"] == []


def test_variance_excludes_an_oracle_whose_version_moved(tmp_path: Path) -> None:
    """A version bump IS a different oracle — calling its change 'variance' would
    launder a deliberate threshold change into noise."""
    store = tmp_path / "verdicts.jsonl"
    v1 = {"test_detector_recall": Needs(
        vertical="finance", datasets=None, from_stage="operating_model", version=1)}
    v2 = {"test_detector_recall": Needs(
        vertical="finance", datasets=None, from_stage="operating_model", version=2)}
    results_store.record_pass("detection-v1", _ledger(status_a="passed"), store=store, reg=v1)
    results_store.record_pass("detection-v1", _ledger(status_a="failed"), store=store, reg=v2)

    group = results_store.variance("detection-v1", store=store)["groups"][0]
    assert group["flapping"] == []
