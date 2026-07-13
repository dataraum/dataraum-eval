"""DAT-743 P3 head-to-head: detector-suite scores on the severity ladder.

RUN FROM THE REPO ROOT ENV after `calibration.run -s clean,tfm-low,tfm-medium,
tfm-high --no-assert` completes (it reads each strategy's sidecar + Postgres
through the same head-resolved path the calibration tests use — never
PhaseLog):

    uv run python tfm/phase1/p3_headtohead.py

One row per entropy_map injection per strategy: the score the injection's
assigned detector produced on its (table, column), plus the best score any
other detector put there. The TFM side of the comparison lives in
p3_anomaly.jsonl (same corpora content: tfm-<level> strategy data is
byte-identical to data/tfm/p3-<level>-s42 by seeded generation).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tfm" / "output" / "phase1" / "p3_headtohead.jsonl"
STRATEGIES = ("tfm-low", "tfm-medium", "tfm-high")


def main() -> None:
    from calibration.conftest import _load_scores_for_strategy
    from calibration.tools._runs import short

    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for strategy in STRATEGIES:
        with (REPO / "data" / strategy / "entropy_map.yaml").open() as fh:
            injections = yaml.safe_load(fh)["injections"]
        scores = _load_scores_for_strategy(strategy)
        merged: dict[tuple[str, str, str], float] = {}
        for (tbl, col, det), score in (scores.column | scores.relationship).items():
            merged[(short(tbl), col, det)] = max(
                score, merged.get((short(tbl), col, det), float("-inf"))
            )

        for inj in injections:
            table = inj["target_file"].removesuffix(".csv")
            column = inj["target_column"]
            det = inj["detector_id"]
            per_col = {d: s for (t, c, d), s in merged.items() if t == table and c == column}
            best_other = {d: s for d, s in per_col.items() if d != det}
            rows.append(
                {
                    "strategy": strategy,
                    "injection_id": inj["injection_id"],
                    "table": table,
                    "column": column,
                    "injection_type": inj["injection_type"],
                    "severity": inj["severity"],
                    "expected_detector": det,
                    "expected_score": per_col.get(det),
                    "best_other": (
                        max(best_other, key=best_other.get) if best_other else None
                    ),
                    "best_other_score": max(best_other.values()) if best_other else None,
                    "n_rows": len(inj["target_rows"]),
                }
            )
        print(f"[h2h] {strategy}: {len(injections)} injections, "
              f"{sum(1 for r in rows if r['strategy'] == strategy and r['expected_score'] is not None)} "
              f"with an expected-detector score")

    with OUT.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print(f"[h2h] wrote {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
