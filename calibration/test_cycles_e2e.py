"""Business-cycle recall/legitimacy vs detected_business_cycles (DAT-680 P1, DAT-686).

Grades the LLM-detected business cycles (``current_detected_business_cycles``) against
the finance-9 corpus's expected cycles (``metadata_truth.cycles``, from the finance
cycle vocabulary + corpus structure). Cycle detection is LLM-inferred, so:

* **recall (HARD on backbone)** — the corpus's structural-backbone cycles
  (``required: true`` — GL posting, accounts-payable) must be detected with their key
  tables. A missing backbone cycle is a real gap. Non-required cycles (e.g.
  period_close, weaker signal) are reported, not asserted. The one relaxation is
  ``STRATEGY_EXPECTED_CYCLE_MISS``: where a strategy's OWN injection destroys the
  evidence a label depends on, the miss is excused — but only while the flow is still
  detected over the same key tables under another label, so the gap stays visible and
  a shape change fails hard.
* **legitimacy (SOFT)** — every detected cycle is a known canonical type over ≥2 real
  corpus tables. A cycle that is neither is a possible hallucination — surfaced (xfail)
  as a ticket/teach scenario, never a hard build-break (no override of the LLM).

Tier-3 (docker + Temporal + LLM): marked ``llm``.
"""

from __future__ import annotations

from typing import Any

import pytest

from calibration import runner as runner_mod
from calibration.metadata_truth import read_detected_cycles
from calibration.tools._runs import workspace_session


@pytest.fixture(autouse=True)
def _scoped_run(strategy_name: str) -> None:
    """Grade ONLY the strategy under test against its own truth (DAT-797)."""
    sidecar = runner_mod.sidecar_path(strategy_name)
    if not sidecar.exists():
        pytest.skip(
            f"no completed run for {strategy_name!r}; run "
            f"`python -m calibration.run -s {strategy_name}` first"
        )
    runner_mod.activate_workspace(strategy_name)


# Backbone cycles a strategy's own injections make ungroundable UNDER THEIR LABEL.
# Key: (strategy, canonical_type) → reason, documented inline.
#
# This is NOT a blanket excuse: the miss is expected only in its documented SHAPE —
# the flow is still detected over the truth's key tables, just under a different
# canonical type. A miss that changes shape (no detected cycle covers those tables
# at all) is a real recall gap and still fails hard. Anti-masking by construction.
STRATEGY_EXPECTED_CYCLE_MISS: dict[tuple[str, str], str] = {
    ("detection-v1", "accounts_payable"): (
        "the strategy's own NAME-0006 injection obscures invoices.vendor_id, so the "
        "per-table annotation layer commits to a customer reading and the cycle agent — "
        "correctly trusting the served meanings — labels the invoice→payment flow "
        "accounts_receivable over the SAME key tables. With the discriminating column "
        "name destroyed, the counterparty direction is not recoverable at the per-table "
        "grain. Pre-existing at the DAT-725 baseline (5/5 runs, both engine versions), "
        "NOT a graph-context regression; lead-ruled an expected miss 2026-07-19. The "
        "upstream fix belongs to the semantic per-table agent (it does too many things "
        "at once — closeout item), not to the cycle agent."
    ),
}


@pytest.mark.llm
def test_cycle_recall(metadata_truth: dict[str, Any], strategy_name: str) -> None:
    """Backbone cycles are detected with their key tables; optional cycles reported."""
    with workspace_session() as session:
        detected = read_detected_cycles(session)

    expected = metadata_truth.get("cycles") or []
    if not expected:
        pytest.skip("no cycles ground truth declared")

    by_type = {d["canonical_type"]: d for d in detected}
    missing_required: list[str] = []
    expected_missing: list[str] = []
    print()
    for e in expected:
        d = by_type.get(e["canonical_type"])
        covered = d is not None and set(e["key_tables"]) <= d["tables"]
        status = "✓" if covered else ("MISSING" if d is None else "key-tables-short")
        print(f"[cycle recall] {e['canonical_type']} (required={e.get('required', False)}): {status}")
        if not e.get("required") or covered:
            continue
        # A documented strategy miss is excused ONLY while its shape holds: some
        # detected cycle — under any label — still covers the truth's key tables.
        reason = STRATEGY_EXPECTED_CYCLE_MISS.get((strategy_name, e["canonical_type"]))
        mislabelled = next(
            (o for o in detected if set(e["key_tables"]) <= o["tables"]),
            None,
        )
        if reason is not None and mislabelled is not None:
            print(
                f"  EXPECTED MISS — the flow is detected as "
                f"{mislabelled['canonical_type']!r} over {sorted(mislabelled['tables'])}"
            )
            expected_missing.append(f"{e['canonical_type']}: {reason}")
        else:
            if reason is not None:
                print(
                    "  documented miss CHANGED SHAPE — no detected cycle covers "
                    f"{sorted(e['key_tables'])}; grading it as a real gap"
                )
            missing_required.append(e["canonical_type"])

    assert not missing_required, (
        "backbone business cycle(s) missing or missing key tables — a real recall gap:\n  "
        + "\n  ".join(missing_required)
    )

    if expected_missing:
        pytest.xfail(
            "backbone cycle(s) detected under the wrong label — a documented, "
            "shape-checked strategy miss:\n  " + "\n  ".join(expected_missing)
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
