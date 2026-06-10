"""The "no orphan detector" lock — keeps detector_coverage.yaml honest (DAT-442).

The scorecard (``detector_coverage.yaml``) is the release scale-proof: every engine
entropy detector on a principled disposition (pool / scalar / informative / candidate)
plus its empirical coverage. This test asserts the scorecard and the engine's REGISTERED
detectors stay in lockstep — a new detector cannot ship undispositioned, and a removed
one cannot linger. Deterministic: the registry is a pure import (no stack, no LLM), so
this is the architectural half of the proof, runnable anywhere.

The coverage cells are deliberately allowed to be ``unverified`` — that is the EMPIRICAL
gap the systematic eval pass closes; this test only guards completeness + well-formedness,
not greenness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from dataraum.entropy.detectors import get_default_registry

_COVERAGE = Path(__file__).parent / "detector_coverage.yaml"

_DISPOSITIONS = {"pool", "scalar", "informative", "candidate"}
_RECALL_PRECISION = {"proven", "baseline", "out_of_slice", "unverified", "n/a"}
_RELIABILITIES = {"real", "placeholder", "n/a"}
_TEACH = {"proven", "wired", "none", "n/a"}
_IN_SLICE = {True, False, "unknown"}


@pytest.fixture(scope="module")
def scorecard() -> dict[str, Any]:
    loaded = yaml.safe_load(_COVERAGE.read_text())
    detectors: dict[str, Any] = loaded["detectors"]
    return detectors


@pytest.fixture(scope="module")
def registered_ids() -> set[str]:
    return {d.detector_id for d in get_default_registry().get_all_detectors()}


def test_every_registered_detector_has_a_disposition(
    scorecard: dict[str, Any], registered_ids: set[str]
) -> None:
    """No orphan detector (registered but undispositioned) and no phantom (charted but gone)."""
    charted = set(scorecard)
    orphans = registered_ids - charted
    phantoms = charted - registered_ids
    assert not orphans, (
        f"detectors registered in the engine but missing from detector_coverage.yaml: "
        f"{sorted(orphans)} — give each a principled disposition before it ships"
    )
    assert not phantoms, (
        f"detectors in detector_coverage.yaml that the engine no longer registers: "
        f"{sorted(phantoms)} — remove the stale rows"
    )


def test_dispositions_are_valid(scorecard: dict[str, Any]) -> None:
    for det, row in scorecard.items():
        assert row.get("disposition") in _DISPOSITIONS, (
            f"{det}: disposition {row.get('disposition')!r} not in {sorted(_DISPOSITIONS)}"
        )


def test_pools_declare_witnesses_and_candidates_declare_entry_criterion(
    scorecard: dict[str, Any],
) -> None:
    """A pool is only a pool if it names >=2 witnesses; a candidate must state its gate."""
    for det, row in scorecard.items():
        disp = row["disposition"]
        if disp == "pool":
            witnesses = row.get("witnesses") or []
            assert len(witnesses) >= 2, (
                f"{det}: a pool must name >=2 independent witnesses, got {witnesses!r}"
            )
        if disp == "candidate":
            assert row.get("entry_criterion"), (
                f"{det}: a candidate must state its entry_criterion (the independent, "
                "grounded 2nd-witness gate) so it can't drift into a contrived pool"
            )


def test_coverage_cells_use_the_allowed_vocab(scorecard: dict[str, Any]) -> None:
    for det, row in scorecard.items():
        cov = row.get("coverage", {})
        assert cov, f"{det}: missing coverage block"
        assert cov.get("recall") in _RECALL_PRECISION, f"{det}: bad recall {cov.get('recall')!r}"
        assert cov.get("precision") in _RECALL_PRECISION, (
            f"{det}: bad precision {cov.get('precision')!r}"
        )
        assert cov.get("reliabilities") in _RELIABILITIES, (
            f"{det}: bad reliabilities {cov.get('reliabilities')!r}"
        )
        assert cov.get("teach_closure") in _TEACH, (
            f"{det}: bad teach_closure {cov.get('teach_closure')!r}"
        )
        assert cov.get("in_slice") in _IN_SLICE, f"{det}: bad in_slice {cov.get('in_slice')!r}"


def test_pools_must_not_claim_real_reliabilities_without_being_calibrated(
    scorecard: dict[str, Any],
) -> None:
    """Consistency guard: only a pool can carry reliabilities; non-pools are n/a."""
    for det, row in scorecard.items():
        rel = row["coverage"]["reliabilities"]
        if row["disposition"] != "pool":
            assert rel == "n/a", f"{det}: non-pool must have reliabilities n/a, got {rel!r}"
