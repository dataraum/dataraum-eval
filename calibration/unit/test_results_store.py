"""Tier-1: the immutable verdict store (DAT-862 slice 1) — append, filter, diff."""

from __future__ import annotations

from pathlib import Path

from calibration import results_store


def _ledger(status_a: str = "passed", status_b: str = "skipped") -> dict[str, dict[str, str]]:
    return {
        "calibration/test_detector_recall.py::test_x": {"status": status_a},
        "calibration/test_ground_truth.py::test_y": {"status": status_b, "reason": "no data"},
        # Tier-1/2 nodeids must never enter the run record:
        "calibration/unit/test_cube.py::test_z": {"status": "passed"},
    }


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
