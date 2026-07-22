"""The per-oracle coverage ledger (Phase 1a) — pure logic, Tier 1.

``build_oracle_ledger`` turns pytest's per-outcome report lists into a
nodeid -> {status, reason?} map. The flat counts it replaces hid which oracle
stood down; this names every one so a silent drop is visible. Tested here with
synthetic reports — no pytest run, no pipeline.
"""

from __future__ import annotations

from calibration.conftest import build_oracle_ledger


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
