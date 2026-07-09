"""Business-cycle recall/legitimacy vs detected_business_cycles (DAT-680 P1, DAT-686).

Grades the LLM-detected business cycles (``current_detected_business_cycles``) against
the finance-9 corpus's expected cycles (``metadata_truth.cycles``, from the finance
cycle vocabulary + corpus structure). Cycle detection is LLM-inferred, so:

* **recall (HARD on backbone)** — the corpus's structural-backbone cycles
  (``required: true`` — GL posting, accounts-payable) must be detected with their key
  tables. A missing backbone cycle is a real gap. Non-required cycles (e.g.
  period_close, weaker signal) are reported, not asserted.
* **legitimacy (SOFT)** — every detected cycle is a known canonical type over ≥2 real
  corpus tables. A cycle that is neither is a possible hallucination — surfaced (xfail)
  as a ticket/teach scenario, never a hard build-break (no override of the LLM).

Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import load_truth, read_detected_cycles
from calibration.tools._runs import workspace_session

_STRATEGY = "clean"


def _activate_or_skip() -> None:
    sidecar = runner_mod.sidecar_path(_STRATEGY)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {_STRATEGY!r}; run "
            f"`python -m calibration.run -s {_STRATEGY}` first"
        )
    runner_mod.activate_workspace(_STRATEGY)


@pytest.mark.llm
def test_cycle_recall() -> None:
    """Backbone cycles are detected with their key tables; optional cycles reported."""
    _activate_or_skip()
    with workspace_session() as session:
        detected = read_detected_cycles(session)

    expected = load_truth().get("cycles") or []
    if not expected:
        pytest.skip("no cycles ground truth declared")

    by_type = {d["canonical_type"]: d for d in detected}
    missing_required: list[str] = []
    print()
    for e in expected:
        d = by_type.get(e["canonical_type"])
        covered = d is not None and set(e["key_tables"]) <= d["tables"]
        status = "✓" if covered else ("MISSING" if d is None else "key-tables-short")
        print(f"[cycle recall] {e['canonical_type']} (required={e.get('required', False)}): {status}")
        if e.get("required") and not covered:
            missing_required.append(e["canonical_type"])

    assert not missing_required, (
        "backbone business cycle(s) missing or missing key tables — a real recall gap:\n  "
        + "\n  ".join(missing_required)
    )


@pytest.mark.llm
def test_cycle_legitimacy() -> None:
    """Detected cycles are known types over ≥2 real tables; soft (LLM-inferred)."""
    _activate_or_skip()
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
