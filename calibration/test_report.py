"""Generate a calibration report after test run.

Writes a YAML summary of recall and precision results to
calibration/reports/{strategy}_{timestamp}.yaml. Reports accumulate
over time to track detector performance across changes.

Run after tests: uv run pytest calibration/ -v && uv run python -m calibration.test_report
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

EVAL_ROOT = Path(__file__).parent.parent
DATA_DIR = EVAL_ROOT / "data"
OUTPUT_DIR = EVAL_ROOT / "output"
REPORTS_DIR = EVAL_ROOT / "calibration" / "reports"


def _load_gate_scores(db_path: Path) -> dict[str, float]:
    """Load gate scores, keyed as 'detector:table.column'."""
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT outputs FROM phase_logs "
        "WHERE phase_name = 'quality_review' "
        "ORDER BY completed_at DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if not row or not row[0]:
        return {}

    outputs = json.loads(row[0])
    column_details = outputs.get("gate_column_details", {})
    id_map = outputs.get("detector_id_map", {})

    scores: dict[str, float] = {}
    for dim_path, targets in column_details.items():
        detector_id = id_map.get(dim_path, dim_path.rsplit(".", 1)[-1])
        for target, score in targets.items():
            ref = target.removeprefix("column:")
            scores[f"{detector_id}:{ref}"] = round(score, 3)
    return scores


def generate_report(strategy: str) -> Path:
    """Generate a calibration report for a strategy run."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load entropy map
    emap_path = DATA_DIR / strategy / "entropy_map.yaml"
    with open(emap_path) as f:
        emap = yaml.safe_load(f)

    # Load injected and clean scores
    injected_scores = _load_gate_scores(OUTPUT_DIR / strategy / "metadata.db")
    clean_db = OUTPUT_DIR / "clean" / "metadata.db"
    clean_scores = _load_gate_scores(clean_db) if clean_db.exists() else {}

    # Compute recall per injection
    threshold = 0.3
    recall_results = []
    for inj in emap.get("injections", []):
        table = inj["target_file"].replace(".csv", "")
        column = inj["target_column"].lower()
        detector = inj["detector_id"]
        key = f"{detector}:{table}.{column}"

        score = injected_scores.get(key)
        clean = clean_scores.get(key, 0.0)
        delta = (score - clean) if score is not None else None

        recall_results.append({
            "injection": inj["injection_type"],
            "detector": detector,
            "target": f"{table}.{column}",
            "score": score,
            "clean_score": clean,
            "delta": round(delta, 3) if delta is not None else None,
            "detected": score is not None and score > threshold,
        })

    detected = sum(1 for r in recall_results if r["detected"])
    testable = sum(
        1 for r in recall_results if r["score"] is not None
    )

    # Compute precision (false alarm rate on clean data)
    false_alarms = [
        {"key": k, "score": v}
        for k, v in sorted(clean_scores.items())
        if v > threshold
    ]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    report = {
        "strategy": strategy,
        "timestamp": timestamp,
        "summary": {
            "recall": f"{detected}/{testable}",
            "recall_rate": round(detected / testable, 2) if testable else 0,
            "clean_false_alarms": len(false_alarms),
            "clean_total_scores": len(clean_scores),
        },
        "recall": recall_results,
        "clean_baseline_above_threshold": false_alarms,
    }

    path = REPORTS_DIR / f"{strategy}_{timestamp}.yaml"
    with open(path, "w") as f:
        yaml.dump(report, f, default_flow_style=False, sort_keys=False)

    print(f"Report: {path}")
    print(f"Recall: {detected}/{testable} ({report['summary']['recall_rate']:.0%})")
    print(f"Clean false alarms: {len(false_alarms)}/{len(clean_scores)}")
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("strategy", nargs="?", default="zone1-detection-v1")
    args = parser.parse_args()
    generate_report(args.strategy)
