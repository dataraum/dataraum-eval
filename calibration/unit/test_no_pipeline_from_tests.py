"""Tier-1: a missing sidecar SKIPS — an assert pass never drives a pipeline (DAT-725).

Run #2's forensics: after ``--reset`` deleted every sidecar, an assert pass
silently ran a complete foreign-strategy pipeline (~4 min of real-LLM spend
outside budget accounting) and left a two-pass workspace state that masked a
recall gap. The sidecar-absent branch of every run-loading helper must raise
pytest's Skipped and never reach ``runner_mod.run_pipeline`` — the runner
(``calibration.run``) is the only pipeline driver.
"""

from __future__ import annotations

import pytest

_BOGUS = "no-such-strategy-dat-725"


def test_missing_sidecar_skips_never_runs_a_pipeline() -> None:
    from calibration.conftest import _require_pipeline_run
    from calibration.test_teach_cycle import _load_run

    for helper in (_require_pipeline_run, _load_run):
        with pytest.raises(pytest.skip.Exception, match="never drive pipelines"):
            helper(_BOGUS)
