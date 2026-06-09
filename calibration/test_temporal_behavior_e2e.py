"""Temporal-behaviour (stock vs flow) — pipeline e2e recall + precision.

The within-run proof through real Temporal + LLM. The teach-first ``temporal_behavior``
detector (DAT-445) pools two witnesses per column — the ontology prior (the concept's
declared ``temporal_behavior``) vs the LLM's INDEPENDENT stock/flow claim, both read off
``SemanticAnnotation`` — and scores their conflict. After a full pipeline run it fires
on ``trial_balance.debit_balance`` (named like a balance → ``account_balance`` prior =
point_in_time/stock, but structurally a per-period FLOW the LLM reads as such → the
witnesses disagree) and stays quiet on ``balance_sheet.ending_balance`` (a genuine
carried-forward STOCK, where prior and claim agree).

RECALL is LLM-nondeterministic: the conflict needs the LLM to claim ``flow`` against the
point_in_time prior; it may instead read ``stock`` from the "balance" name, agreeing with
the prior. So recall is ``xfail(strict=False)`` (XPASS when it lands), the same posture
as ``business_meaning``. Precision is robust (``ending_balance`` is an unambiguous stock)
and asserted strictly.
"""

from __future__ import annotations

import pytest

_DETECTOR = "temporal_behavior"
_RECALL = ("trial_balance", "debit_balance", _DETECTOR)
_PRECISION = ("balance_sheet", "ending_balance", _DETECTOR)
_MARGIN = 0.05


@pytest.mark.llm
@pytest.mark.xfail(
    reason="recall needs the LLM to CLAIM flow on debit_balance against the "
    "account_balance=point_in_time prior; it may read stock from the 'balance' name and "
    "agree with the prior — nondeterministic, like business_meaning",
    strict=False,
)
def test_recall_debit_balance_flow_named_balance_fires(
    pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """trial_balance.debit_balance: a per-period flow whose prior says stock → conflict."""
    recall = pipeline_scores.get(_RECALL)
    precision = pipeline_scores.get(_PRECISION, 0.0)
    assert recall is not None, "temporal_behavior did not score trial_balance.debit_balance"
    assert recall > precision + _MARGIN, (
        f"recall C={recall:.3f} did not exceed precision C={precision:.3f} by > {_MARGIN}"
    )


@pytest.mark.llm
def test_precision_ending_balance_genuine_stock_quiet(
    pipeline_scores: dict[tuple[str, str, str], float],
) -> None:
    """balance_sheet.ending_balance: a genuine stock claimed as a balance → quiet.

    Either no object (the witnesses agree, nothing to surface) or a low conflict —
    never a high one. ``ending_balance`` matches only the balance concept, so this
    leg is deterministic.
    """
    precision = pipeline_scores.get(_PRECISION)
    if precision is None:
        pytest.skip("temporal_behavior emitted no object for balance_sheet.ending_balance")
    assert precision < 0.2, f"genuine stock should stay quiet, got C={precision:.3f}"
