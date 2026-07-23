"""Business-cycle recall/legitimacy vs detected_business_cycles (DAT-680 P1, DAT-686).

Grades the LLM-detected business cycles (``current_detected_business_cycles``) against
the finance-9 corpus's expected cycles (``metadata_truth.cycles``, from the finance
cycle vocabulary + corpus structure). Cycle detection is LLM-inferred, so:

* **recall (HARD on backbone), THREE-STATE for directed cycles (DAT-856, v2)** —
  the corpus's structural-backbone cycles (``required: true``) must be detected
  with their key tables. A truth entry carrying ``family`` + ``direction``
  (declared from the vertical's family declaration — never a truth patch) grades
  three named states:

  - ``CORRECT``           — canonical_type detected, key tables covered, direction matches;
  - ``DETECTED_BUT_UNDIRECTED`` — the FAMILY row exists with
    ``direction='undetermined'`` (engine Cut B renders an undirected detection as
    canonical_type = the family). STILL FAILS a required directed cycle — but as
    its own named failure state, distinguishable from a miss, with the missing
    evidence named from the cycle's own description. This is how the carried AP
    acceptance becomes measurable instead of a standing red.
  - ``MISSED`` / key-tables-short — as before.
* **legitimacy (SOFT)** — every detected cycle is a known canonical type over ≥2 real
  corpus tables. A cycle that is neither is a possible hallucination — surfaced (xfail)
  as a ticket/teach scenario, never a hard build-break (no override of the LLM).

version=2: three-state directed grading + the family/direction loader columns —
one coordinated verdict-changing bump (the sweep-#3 vocabulary co-evolution).

Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import cube
from calibration.conftest import require_pipeline_run
from calibration.metadata_truth import read_detected_cycles
from calibration.tools._runs import workspace_session

pytestmark = cube.needs(vertical="finance", dataset="*", from_stage="operating_model", version=2)


def classify_directed_cycle(
    expected: dict[str, Any], detected: list[dict[str, Any]]
) -> tuple[str, str]:
    """Three-state verdict for one expected DIRECTED cycle (pure; Tier-1-able).

    Returns ``(state, detail)`` with state ∈ {CORRECT, DETECTED_BUT_UNDIRECTED,
    MISSED, KEY_TABLES_SHORT, WRONG_DIRECTION}. WRONG_DIRECTION (a directed row
    whose direction contradicts the declared truth) is graded as its own state
    too — it is neither correct nor undetermined.
    """
    want_tables = set(expected["key_tables"])
    exact = [d for d in detected if d["canonical_type"] == expected["canonical_type"]]
    if exact:
        d = exact[0]
        if not want_tables <= d["tables"]:
            return "KEY_TABLES_SHORT", (
                f"detected but tables {sorted(d['tables'])} miss {sorted(want_tables - d['tables'])}"
            )
        if d["direction"] == expected["direction"]:
            return "CORRECT", f"direction={d['direction']}"
        if d["direction"] == "undetermined":
            return "DETECTED_BUT_UNDIRECTED", d.get("cycle_name") or ""
        return "WRONG_DIRECTION", f"detected {d['direction']!r}, declared {expected['direction']!r}"
    # Cut B: an undirected detection renders as canonical_type = the family.
    family_rows = [
        d
        for d in detected
        if expected.get("family")
        and (d["canonical_type"] == expected["family"] or d.get("family") == expected["family"])
    ]
    if family_rows:
        d = family_rows[0]
        if d["direction"] in (None, "undetermined"):
            return "DETECTED_BUT_UNDIRECTED", d.get("cycle_name") or ""
        return "WRONG_DIRECTION", f"family row direction {d['direction']!r}"
    return "MISSED", ""


@pytest.fixture(autouse=True)
def _scoped_run(strategy_name: str) -> None:
    """Grade ONLY the strategy under test against its own truth (DAT-797)."""
    require_pipeline_run(strategy_name)


@pytest.mark.llm
def test_cycle_recall(metadata_truth: dict[str, Any]) -> None:
    """Backbone cycles are detected with their key tables; DIRECTED cycles grade
    three-state (DAT-856); optional cycles reported."""
    with workspace_session() as session:
        detected = read_detected_cycles(session)

    expected = metadata_truth.get("cycles") or []
    if not expected:
        pytest.skip("no cycles ground truth declared")

    by_type = {d["canonical_type"]: d for d in detected}
    failures: list[str] = []
    print()
    for e in expected:
        if e.get("direction"):
            state, detail = classify_directed_cycle(e, detected)
            print(
                f"[cycle recall] {e['canonical_type']} (required={e.get('required', False)}, "
                f"directed): {state}" + (f" — {detail}" if detail else "")
            )
            if e.get("required") and state != "CORRECT":
                failures.append(f"{e['canonical_type']}: {state}" + (f" ({detail})" if detail else ""))
            continue
        d = by_type.get(e["canonical_type"])
        covered = d is not None and set(e["key_tables"]) <= d["tables"]
        status = "✓" if covered else ("MISSING" if d is None else "key-tables-short")
        print(f"[cycle recall] {e['canonical_type']} (required={e.get('required', False)}): {status}")
        if e.get("required") and not covered:
            failures.append(f"{e['canonical_type']}: {status}")

    assert not failures, (
        "backbone business cycle(s) not correctly detected — each failure carries its "
        "NAMED state (DETECTED_BUT_UNDIRECTED is a direction gap, distinct from MISSED):\n  "
        + "\n  ".join(failures)
    )


@pytest.mark.llm
def test_cycle_legitimacy() -> None:
    """Detected cycles are known types over ≥2 real tables; soft (LLM-inferred)."""
    with workspace_session() as session:
        detected = read_detected_cycles(session)

    if not detected:
        pytest.skip("no business cycles detected")

    suspect = [d for d in detected if not d["is_known_type"] or len(d["tables"]) < 2]
    print(f"\n[cycle legitimacy] {len(detected) - len(suspect)}/{len(detected)} detected cycles look legitimate")
    for d in suspect:
        print(f"  SUSPECT: {d['canonical_type']!r} known={d['is_known_type']} tables={sorted(d['tables'])}")

    if suspect:
        pytest.xfail(
            "detected cycle(s) not a known canonical type or spanning <2 real tables — "
            "possible hallucination (LLM-inferred; a ticket/teach scenario, not a defect):\n  "
            + "\n  ".join(f"{d['canonical_type']!r} tables={sorted(d['tables'])}" for d in suspect)
        )
