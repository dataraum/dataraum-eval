"""Regenerate calibration/fixtures/metadata_truth.yaml from the testdata generator.

DAT-682 made dataraum-testdata the single source of the agent-layer ground truth
(``canonical_metadata_truth()``). This script rewrites the committed eval fixture from
that source; ``test_metadata_truth.py::test_fixture_matches_generator`` guards drift.

    uv run python scripts/regen_metadata_truth.py
"""

from __future__ import annotations

from pathlib import Path

from testdata.metadata_truth import export_metadata_truth

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "calibration" / "fixtures"


def main() -> None:
    export_metadata_truth(FIXTURE_DIR)
    print(f"wrote {FIXTURE_DIR / 'metadata_truth.yaml'}")


if __name__ == "__main__":
    main()
