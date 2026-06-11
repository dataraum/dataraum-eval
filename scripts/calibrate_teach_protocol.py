"""Relationship teach-protocol calibration — the human witnesses' rig (DAT-447).

Closes the circuit's measurement segment: the system asks for verdicts
(relationship_discovery's teach suggestions), the verdicts become witnesses
(confirm → manual, keep → keeper, beside the llm rows), and THIS protocol
measures those witnesses. Verdicts are driven by the corpus ground truth — a
simulated teacher — so the measured accuracy is a PLUMBING CEILING, not a
human-error estimate: it proves verdict → row → witness → pool end to end.
Ship with that disclosure; per Philipp (2026-06-11) the human error rate is
assumed "quite low but not zero" — Laplace smoothing encodes the not-zero
structurally ((1+n)/(2+n) < 1; a witness at r=1.0 would be a deterministic
override wearing a witness costume). Real human reliability replaces the
ceiling when the context lane's test users accumulate verdicts.

Protocol over detection-relationship-cal-v1 (run the strategy first):
  1. Split the GENUINE labelled pairs deterministically (sorted by child
     column, alternating): half get ``confirm`` (→ manual), half ``keep``
     (→ keeper). Spurious pairs get no verdict — the selector already
     rejected them out of the catalog, and the simulated teacher follows
     ground truth.
  2. teach_relationships_and_rerun: overlays written, same session re-driven.
  3. The wave-2 rig's relationship adapter then reads the post-teach claim
     rows; manual_curation / keeper_retention vote for the first time.

    uv run python scripts/calibrate_teach_protocol.py            # teach + re-run
    uv run python scripts/calibrate_wave2_reliabilities.py relationship  # measure

Print-only end to end: reliabilities.yaml is hand-curated with provenance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

EVAL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EVAL_ROOT))

from calibration import runner as runner_mod  # noqa: E402
from calibration.conftest import DATA_DIR  # noqa: E402

_STRATEGY = "detection-relationship-cal-v1"


def planned_verdicts() -> list[dict[str, str]]:
    """Deterministic verdict plan from the corpus ground truth (genuine pairs only)."""
    emap = yaml.safe_load((DATA_DIR / _STRATEGY / "entropy_map.yaml").read_text())
    genuine = sorted(
        (
            inj["parameters"]
            for inj in emap["injections"]
            if inj.get("injection_type") == "inject_relationship_pairs"
            and inj["parameters"]["label"] == "genuine"
        ),
        key=lambda p: str(p["child_column"]),
    )
    verdicts = []
    for i, p in enumerate(genuine):
        verdicts.append(
            {
                "action": "confirm" if i % 2 == 0 else "keep",
                "from_table": str(p["child_table"]),
                "from_column": str(p["child_column"]),
                "to_table": str(p["parent_table"]),
                "to_column": str(p["parent_column"]),
            }
        )
    return verdicts


def main() -> None:
    sidecar = runner_mod.sidecar_path(_STRATEGY)
    if not sidecar.exists():
        raise SystemExit(f"no completed run for {_STRATEGY} — run the strategy first")
    run = runner_mod.CalibrationRun.from_json(sidecar.read_text())

    verdicts = planned_verdicts()
    n_confirm = sum(1 for v in verdicts if v["action"] == "confirm")
    print(
        f"[protocol] {len(verdicts)} ground-truth verdicts on genuine pairs: "
        f"{n_confirm} confirm (→ manual) / {len(verdicts) - n_confirm} keep (→ keeper)"
    )
    runner_mod.teach_relationships_and_rerun(run, verdicts=verdicts)
    print(
        "[protocol] re-run complete — measure with: "
        "uv run python scripts/calibrate_wave2_reliabilities.py relationship"
    )


if __name__ == "__main__":
    main()
