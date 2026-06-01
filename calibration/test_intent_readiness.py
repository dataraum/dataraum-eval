"""Intent-readiness calibration — does the network roll detector scores up to
the right query / aggregation / reporting readiness?

The entropy network (``network.yaml``) combines detector scores into three
intent readiness signals, banded ready < investigate < blocked. This test is the
oracle the network never had: for each known injection, ``intent_readiness.yaml``
states the FLOOR readiness the affected column must reach for each compromised
intent. We assert the network reports at least that — a recall check on the
rollup. Precision: on the clean baseline every column must read "ready".

This is implementation-agnostic. It validated the pgmpy BBN and continues to
guard the deterministic noisy-OR rollup that replaces it — the contract is the
readiness output, not the inference engine.

Slice / known-issue gating reuses test_detector_recall.py so there is one source
of truth for what the current addSourceWorkflow slice runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from calibration.test_detector_recall import (
    CURRENT_SLICE_DETECTORS,
    KNOWN_MISALIGNED,
    LLM_NONDETERMINISTIC,
    NOT_IMPLEMENTED,
    OUT_OF_SLICE_REASON,
)

EVAL_ROOT = Path(__file__).parent.parent
EXPECTATIONS_PATH = Path(__file__).parent / "intent_readiness.yaml"

# ready < investigate < blocked
_RANK = {"ready": 0, "investigate": 1, "blocked": 2}


def _load_expectations(strategy: str) -> dict[str, Any]:
    if not EXPECTATIONS_PATH.exists():
        return {}
    with open(EXPECTATIONS_PATH) as f:
        data = yaml.safe_load(f) or {}
    result: dict[str, Any] = data.get(strategy, {}) or {}
    return result


def _expectation_id(exp: dict[str, Any]) -> str:
    return f"{exp['driver']}:{exp['target']}"


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize one case per expectation for the selected strategy."""
    if "expectation" in metafunc.fixturenames:
        strategy = metafunc.config.getoption("--strategy", default="detection-v1")
        exps = _load_expectations(strategy).get("expectations", [])
        ids = [_expectation_id(e) for e in exps]
        metafunc.parametrize("expectation", exps, ids=ids)


def test_intent_readiness_floor(
    expectation: dict[str, Any],
    network_readiness: dict[tuple[str, str], dict[str, str]],
    request: pytest.FixtureRequest,
) -> None:
    """Each injection must push the affected column to at least its floor readiness."""
    table, column = expectation["target"].split(".", 1)
    driver = expectation["driver"]

    # Same gating as detector recall — skip / xfail before asserting.
    if driver in NOT_IMPLEMENTED:
        pytest.skip(f"{driver} not implemented yet")
    if driver not in CURRENT_SLICE_DETECTORS:
        pytest.skip(
            OUT_OF_SLICE_REASON.get(
                driver, f"{driver}: phase not yet wired into the addSourceWorkflow slice"
            )
        )
    if driver in KNOWN_MISALIGNED:
        pytest.xfail(f"{driver} injection is known-misaligned (see CLAUDE.md)")
    if (driver, table, column) in LLM_NONDETERMINISTIC:
        request.node.add_marker(
            pytest.mark.xfail(reason=LLM_NONDETERMINISTIC[(driver, table, column)], strict=False)
        )

    # Pipeline lowercases column names on import.
    readiness = network_readiness.get((table, column.lower()))
    assert readiness is not None, (
        f"no network readiness for {table}.{column} — column produced no node "
        f"evidence (driver={driver} may map to a direct signal, not a network node)"
    )

    for intent, floor in expectation["min_readiness"].items():
        actual = readiness.get(intent)
        assert actual is not None, (
            f"{intent} not reported for {table}.{column} — intent had no resolved "
            f"parents from the observed evidence"
        )
        assert _RANK[actual] >= _RANK[floor], (
            f"{table}.{column} {intent}: expected >= {floor}, got {actual} "
            f"(injection {driver} should have degraded {intent}; note: {expectation.get('note', '')})"
        )


def _clean_baseline() -> dict[str, dict[str, str]]:
    """Captured clean-data readiness baseline (target → {intent: readiness})."""
    if not EXPECTATIONS_PATH.exists():
        return {}
    with open(EXPECTATIONS_PATH) as f:
        data = yaml.safe_load(f) or {}
    result: dict[str, dict[str, str]] = data.get("clean_readiness", {}) or {}
    return result


def test_clean_readiness_no_regression(
    clean_network_readiness: dict[tuple[str, str], dict[str, str]],
) -> None:
    """Precision: no clean column reads WORSE than its captured baseline.

    Clean financial data legitimately produces non-ready signals (nullable
    columns, non-Benford distributions, undeclared units) that the network
    correctly surfaces — see ``clean_readiness`` in intent_readiness.yaml. This
    catches a *regression*: a clean column whose readiness exceeds baseline (a
    new false alarm), mirroring test_detector_precision.py's baseline model.
    """
    baseline = _clean_baseline()

    regressions: list[str] = []
    for (tbl, col), intents in sorted(clean_network_readiness.items()):
        expected = baseline.get(f"{tbl}.{col}", {})
        for intent, actual in sorted(intents.items()):
            floor = expected.get(intent, "ready")
            if _RANK[actual] > _RANK[floor]:
                regressions.append(f"  {tbl}.{col} {intent}: {actual} (baseline {floor})")

    assert not regressions, (
        "clean columns read worse than baseline (new false readiness alarms):\n"
        + "\n".join(regressions)
        + "\n\nIf expected, update `clean_readiness` in calibration/intent_readiness.yaml."
    )
