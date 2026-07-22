"""Wild-lane routing + summary rendering (Phase 3) — Tier 1, no pipeline.

Locks the seams the wild front-door adds to calibration.run: which targets route to the
wild lane, the LLM-call cost proxy, and that the run summary surfaces the fire-rate
scoreboard's findings. None of this drives a pipeline.
"""

from __future__ import annotations

import pytest

from calibration import run as run_mod


def test_finance_strategy_is_not_wild() -> None:
    # A name that resolves to strategies/<name>.yaml always takes the synthetic lane.
    assert run_mod._is_wild_target("clean") is False
    assert run_mod._is_wild_target("detection-v1") is False


def test_registered_corpus_is_wild() -> None:
    # rel-f1 is declared in the committed corpus registry → wild, regardless of staging.
    assert run_mod._is_wild_target("rel-f1") is True


def test_unknown_target_is_neither() -> None:
    assert run_mod._is_wild_target("zzz-not-a-real-target") is False


def test_llm_call_count_is_none_for_unrun_target() -> None:
    assert run_mod._llm_call_count("zzz-not-a-real-target") is None


def test_summary_renders_wild_scoreboard_findings(capsys: pytest.CaptureFixture[str]) -> None:
    summary = run_mod.Summary(
        outcomes=[
            run_mod.Outcome(
                strategy="rel-f1",
                ran=True,
                asserted=None,
                tier="wild",
                llm_calls=40,
                scoreboard={
                    "mute": ["derived_value"],
                    "never_fired": ["type_fidelity"],
                    "saturated": ["benford"],
                },
            )
        ]
    )
    summary.print()
    out = capsys.readouterr().out
    assert "[wild, 40 llm-calls]" in out  # the cost line
    assert "wild scoreboard" in out
    assert "MUTE: derived_value" in out and "SATURATED: benford" in out
    assert "filed Finding" in out  # points at findings.py, never an engine patch


def test_summary_wild_scoreboard_no_flags_is_stated(capsys: pytest.CaptureFixture[str]) -> None:
    summary = run_mod.Summary(
        outcomes=[
            run_mod.Outcome(
                strategy="rel-f1", ran=True, tier="wild",
                scoreboard={"mute": [], "never_fired": [], "saturated": []},
            )
        ]
    )
    summary.print()
    assert "no flags (read the distribution)" in capsys.readouterr().out
