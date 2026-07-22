"""Adjudication-entropy recall — ORDERING grammar, not point thresholds (ADR-0009).

Pooled/adjudication detectors (``null_semantics``, and the unit / temporal_behavior
measurements to come) are graded by whether an injection RAISES the conflict over
the clean baseline — never by ``score > 0.3``, which is exactly the Goodhart trap
the framework exists to avoid (a legitimate conflict of 0.25 is real signal, and a
point threshold would either fail it or pressure us to inflate it).

The token pool is generative (strategy-supplied), so these assertions never
reference specific tokens or score values — only the injected-vs-clean ordering.

Run with: ``--strategy detection-null-v1``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import cube

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="add_source", baseline=("clean",))

# Anti-noise margin on the DELTA (injected − clean), NOT a calibrated detection
# threshold on the absolute conflict. ADR-0009: orderings/deltas, never point
# thresholds to be constant-tuned.
_CONFLICT_MARGIN = 0.05

ADJUDICATION_DETECTORS = frozenset({"null_semantics"})


def _adjudication_injections(injections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in injections if i.get("detector_id") in ADJUDICATION_DETECTORS]


def test_injection_raises_conflict_over_clean(
    injections: list[dict[str, Any]],
    pipeline_scores: dict[tuple[str, str, str], float],
    clean_pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """Each null-token injection raises null_semantics conflict above its clean self.

    Ordering grammar: ``injected_C > clean_C + margin``. The clean run has no
    injected tokens, so the column quarantines nothing and null_semantics never
    fires there (clean ≈ 0) — the injection is what creates the contested tokens.
    """
    adjudications = _adjudication_injections(injections)
    if not adjudications:
        pytest.skip("no adjudication-detector injections in this strategy")

    failures: list[str] = []
    for inj in adjudications:
        table = inj["target_file"].replace(".csv", "")
        column = inj["target_column"].lower()  # pipeline lowercases on import
        detector = inj["detector_id"]

        injected = pipeline_scores.get((table, column, detector))
        clean = clean_pipeline_scores.get((table, column, detector), 0.0)

        if injected is None:
            failures.append(f"{detector} did not fire on {table}.{column} (no score)")
        elif injected - clean <= _CONFLICT_MARGIN:
            failures.append(
                f"{detector} on {table}.{column}: injected C={injected:.3f} did not exceed "
                f"clean C={clean:.3f} by > {_CONFLICT_MARGIN} (delta={injected - clean:+.3f})"
            )

    assert not failures, "adjudication recall (ordering) failed:\n" + "\n".join(failures)
