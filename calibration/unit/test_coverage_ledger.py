"""The coverage ledger + baseline diff (Phase 1) — pure logic, Tier 1.

``build_oracle_ledger`` turns pytest's per-outcome report lists into a
nodeid -> {status, reason?} map; ``diff_against_baseline`` flags oracles that
graded in the blessed baseline and stand down now (a coverage regression to
triage). Tested with synthetic reports — no pytest run, no pipeline.
"""

from __future__ import annotations

from calibration.coverage import (
    build_oracle_ledger,
    diff_against_baseline,
    graded_nodeids,
)


class _Rep:
    """Minimal stand-in for a pytest TestReport (only what the ledger reads)."""

    def __init__(self, nodeid: str, longrepr: object = None) -> None:
        self.nodeid = nodeid
        self.longrepr = longrepr


def test_ledger_names_each_oracle_with_status() -> None:
    stats = {
        "passed": [_Rep("t.py::a")],
        "skipped": [_Rep("t.py::b", ("t.py", 5, "Skipped: Tier-B corpus declares no roles"))],
        "failed": [_Rep("t.py::c")],
    }
    led = build_oracle_ledger(stats)
    assert led["t.py::a"] == {"status": "passed"}
    assert led["t.py::b"] == {"status": "skipped", "reason": "Tier-B corpus declares no roles"}
    assert led["t.py::c"] == {"status": "failed"}


def test_failure_beats_passed_setup_for_same_nodeid() -> None:
    """A failing test has a passed setup report AND a failed call report under one
    nodeid — the definitive outcome (failed) must win."""
    stats = {"passed": [_Rep("t.py::x")], "failed": [_Rep("t.py::x")]}
    assert build_oracle_ledger(stats)["t.py::x"]["status"] == "failed"


def test_error_beats_everything() -> None:
    stats = {"passed": [_Rep("t.py::x")], "skipped": [_Rep("t.py::x")], "error": [_Rep("t.py::x")]}
    assert build_oracle_ledger(stats)["t.py::x"]["status"] == "error"


def test_skip_reason_handles_nontuple_longrepr() -> None:
    stats = {"skipped": [_Rep("t.py::y", "Skipped: plain string reason")]}
    assert build_oracle_ledger(stats)["t.py::y"]["reason"] == "plain string reason"


def test_graded_oracles_carry_no_reason() -> None:
    led = build_oracle_ledger({"passed": [_Rep("t.py::a")], "failed": [_Rep("t.py::b")]})
    assert "reason" not in led["t.py::a"]
    assert "reason" not in led["t.py::b"]


def test_graded_nodeids_excludes_skips_and_errors() -> None:
    ledger = {
        "a": {"status": "passed"},
        "b": {"status": "failed"},
        "c": {"status": "xfailed", "reason": "x"},
        "d": {"status": "xpassed"},
        "e": {"status": "skipped", "reason": "y"},
        "f": {"status": "error"},
    }
    assert graded_nodeids(ledger) == {"a", "b", "c", "d"}


def test_diff_flags_regressions_and_gains() -> None:
    baseline = ["a", "b", "c"]
    ledger = {
        "a": {"status": "passed"},                          # still graded
        "b": {"status": "skipped", "reason": "stood down"}, # REGRESSED (now skips)
        # "c" absent entirely                               # REGRESSED (vanished)
        "d": {"status": "passed"},                          # GAINED
    }
    diff = diff_against_baseline(baseline, ledger)
    assert diff["regressed"] == ["b", "c"]
    assert diff["gained"] == ["d"]


def test_no_regression_when_coverage_matches() -> None:
    baseline = ["a", "b"]
    ledger = {"a": {"status": "passed"}, "b": {"status": "failed"}}
    assert diff_against_baseline(baseline, ledger) == {"regressed": [], "gained": []}
