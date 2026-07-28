"""Coverage accounting — the per-oracle ledger and the baseline diff (Phase 1).

Pure functions, no pytest, no docker: importable by both the pytest terminal-summary
hook (``conftest.pytest_terminal_summary``) and the runner summary (``run.py``). The
ledger names what graded; the baseline diff flags what STOPPED grading.

A coverage regression is a FINDING TO TRIAGE, never an automatic engine-blame. An
oracle that graded in the blessed baseline and stands down now can mean, equally:

  * the oracle is wrongly skipping — a test-suite / stale-eval bug (ours), OR
  * the engine stopped producing what the oracle grades — an engine bug, OR
  * the baseline was blessed at a bad state — the baseline itself is wrong.

The diff surfaces the drop and names all three; it does not decide which, and it
does not fail the run. Re-bless with ``calibration.run --bless-coverage`` once the
new coverage is understood and correct.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from calibration.verdict_values import values_from

BASELINES_DIR = Path(__file__).parent / "coverage_baselines"

# Report categories a test can land in; severity order so a failed/errored call
# beats the same test's passed setup report when both share one nodeid.
_LEDGER_ORDER = ("passed", "xpassed", "xfailed", "skipped", "failed", "error")

# "Graded" = the oracle RAN and reached a verdict. A skip stood down; an error broke.
_GRADED = frozenset({"passed", "failed", "xfailed", "xpassed"})


def _skip_reason(report: Any) -> str:
    """The human reason from a skipped/xfailed report's longrepr."""
    raw = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
    return raw.removeprefix("Skipped: ").removeprefix("xfail: ").strip()


def build_oracle_ledger(stats: dict[str, list[Any]]) -> dict[str, dict[str, Any]]:
    """Per-oracle outcome map: nodeid -> {status, reason?, values?}.

    The flat pass/skip COUNTS hid which oracle stood down — a whole oracle could
    vanish behind a bumped skip tally and the run still read clean. This names every
    one, so a silently-dropped oracle is visible and diffable against a baseline.
    Severity order (``_LEDGER_ORDER``) makes a failed/errored call beat the same
    test's passed setup report when both land under one nodeid.

    ``values`` carries the oracle's measured numbers and the thresholds that judged
    them (DAT-862 / RFC 5 ext 1, ``verdict_values.record``) — the margin, not just
    whether it held. Absent when the oracle recorded none.
    """
    ledger: dict[str, dict[str, Any]] = {}
    for status in _LEDGER_ORDER:
        for report in stats.get(status, []):
            entry: dict[str, Any] = {"status": status}
            if status in ("skipped", "xfailed"):
                entry["reason"] = _skip_reason(report)
            values = values_from(getattr(report, "user_properties", None))
            if values:
                entry["values"] = values
            ledger[report.nodeid] = entry
    return ledger


def graded_nodeids(ledger: dict[str, dict[str, Any]]) -> set[str]:
    """The oracles that reached a verdict (ran, didn't stand down or break)."""
    return {nid for nid, e in ledger.items() if e.get("status") in _GRADED}


def diff_against_baseline(
    baseline: list[str] | set[str], ledger: dict[str, dict[str, Any]]
) -> dict[str, list[str]]:
    """Compare this run's graded set to the blessed baseline.

    Returns ``{"regressed": [...], "gained": [...]}``:
      * regressed — graded in the baseline, NOT graded now (skipped / errored /
        absent). The coverage regression to TRIAGE (test-suite bug vs engine bug vs
        a wrong baseline), never an automatic engine defect.
      * gained — graded now, absent from the baseline. New coverage; bless to adopt.
    """
    base = set(baseline)
    now = graded_nodeids(ledger)
    return {"regressed": sorted(base - now), "gained": sorted(now - base)}


def baseline_file(strategy: str) -> Path:
    return BASELINES_DIR / f"{strategy}.json"


def load_baseline(strategy: str) -> list[str] | None:
    """The blessed graded-set for a strategy, or None if never blessed."""
    path = baseline_file(strategy)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    graded = data.get("graded")
    return graded if isinstance(graded, list) else None


def save_baseline(strategy: str, ledger: dict[str, dict[str, Any]]) -> Path:
    """Bless this run's graded-set as the strategy's baseline (a committed reference)."""
    path = baseline_file(strategy)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"strategy": strategy, "graded": sorted(graded_nodeids(ledger))}
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path
