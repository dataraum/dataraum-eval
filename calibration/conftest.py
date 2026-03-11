"""Calibration test fixtures.

Loads entropy_map.yaml, ground_truth.yaml, and pipeline output for assertions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

EVAL_ROOT = Path(__file__).parent.parent
DATA_DIR = EVAL_ROOT / "data"
OUTPUT_DIR = EVAL_ROOT / "output"


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def entropy_map() -> dict[str, Any]:
    """Load entropy_map.yaml from medium testdata."""
    path = DATA_DIR / "medium" / "entropy_map.yaml"
    if not path.exists():
        pytest.skip(f"No entropy_map at {path} — run testdata generate first")
    return _load_yaml(path)


@pytest.fixture(scope="session")
def ground_truth() -> dict[str, Any]:
    """Load ground_truth.yaml from medium testdata."""
    path = DATA_DIR / "medium" / "ground_truth.yaml"
    if not path.exists():
        pytest.skip(f"No ground_truth at {path} — run testdata generate first")
    return _load_yaml(path)


@pytest.fixture(scope="session")
def injections(entropy_map: dict[str, Any]) -> list[dict[str, Any]]:
    """List of injection dicts from entropy_map."""
    return entropy_map.get("injections", [])


@pytest.fixture(scope="session")
def medium_pipeline_scores() -> dict[tuple[str, str, str], float]:
    """Load detector scores from medium pipeline output.

    Returns dict of (table, column, detector_id) → score.
    Reads from the metadata.db produced by the pipeline.
    """
    db_path = OUTPUT_DIR / "medium" / "metadata.db"
    if not db_path.exists():
        pytest.skip(f"No pipeline output at {db_path} — run pipeline first")

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT target, detector_id, score
            FROM entropy_objects
            WHERE target LIKE 'column:%'
            """
        ).fetchall()
    except sqlite3.OperationalError:
        pytest.skip("entropy_objects table not found in metadata.db")
    finally:
        conn.close()

    scores: dict[tuple[str, str, str], float] = {}
    for target, detector_id, score in rows:
        # target format: "column:{table}.{column}"
        ref = target.removeprefix("column:")
        parts = ref.split(".", 1)
        if len(parts) == 2:
            table, column = parts
            key = (table, column, detector_id)
            # Keep highest score if multiple objects exist
            if key not in scores or score > scores[key]:
                scores[key] = score

    return scores


@pytest.fixture(scope="session")
def clean_pipeline_scores() -> dict[tuple[str, str, str], float]:
    """Load detector scores from clean pipeline output."""
    db_path = OUTPUT_DIR / "clean" / "metadata.db"
    if not db_path.exists():
        pytest.skip(f"No clean pipeline output at {db_path} — run pipeline first")

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT target, detector_id, score
            FROM entropy_objects
            WHERE target LIKE 'column:%'
            """
        ).fetchall()
    except sqlite3.OperationalError:
        pytest.skip("entropy_objects table not found in metadata.db")
    finally:
        conn.close()

    scores: dict[tuple[str, str, str], float] = {}
    for target, detector_id, score in rows:
        ref = target.removeprefix("column:")
        parts = ref.split(".", 1)
        if len(parts) == 2:
            table, column = parts
            key = (table, column, detector_id)
            if key not in scores or score > scores[key]:
                scores[key] = score

    return scores
