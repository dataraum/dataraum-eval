"""Generate a calibration report after test run.

Writes a YAML summary of recall and precision results to
calibration/reports/{strategy}_{timestamp}.yaml. Reports accumulate
over time to track detector performance across changes.

Run after tests: uv run pytest calibration/ -v && uv run python -m calibration.test_report
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

EVAL_ROOT = Path(__file__).parent.parent
DATA_DIR = EVAL_ROOT / "data"
OUTPUT_DIR = EVAL_ROOT / "output"
REPORTS_DIR = EVAL_ROOT / "calibration" / "reports"


def _load_scores(output_dir: Path) -> dict[str, float]:
    """Load detector scores via measure_entropy(), keyed as 'detector:table.column'."""
    from calibration.conftest import _load_scores

    gate = _load_scores(output_dir)
    scores: dict[str, float] = {}
    for (table, column, detector), score in gate.column.items():
        scores[f"{detector}:{table}.{column}"] = round(score, 3)
    for (table, detector), score in gate.table.items():
        scores[f"{detector}:{table}"] = round(score, 3)
    return scores


def generate_report(strategy: str) -> Path:
    """Generate a calibration report for a strategy run."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load entropy map
    emap_path = DATA_DIR / strategy / "entropy_map.yaml"
    with open(emap_path) as f:
        emap = yaml.safe_load(f)

    # Load injected and clean scores
    injected_scores = _load_scores(OUTPUT_DIR / strategy)
    clean_dir = OUTPUT_DIR / "clean"
    clean_scores = _load_scores(clean_dir) if (clean_dir / "metadata.db").exists() else {}

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

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

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
    recall_rate = round(detected / testable, 2) if testable else 0
    print(f"Recall: {detected}/{testable} ({recall_rate:.0%})")
    print(f"Clean false alarms: {len(false_alarms)}/{len(clean_scores)}")
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("strategy", nargs="?", default="zone1-detection-v1")
    args = parser.parse_args()
    generate_report(args.strategy)
