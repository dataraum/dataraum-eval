"""Batch calibration runner — the S0 spine: one command, many strategies, one scoreboard.

    caffeinate -dims uv run python -m calibration.batch clean detection-v1 --seed 42

Per strategy, in order: generate (testdata, cheap) -> pipeline (Temporal +
real LLM, the expensive step) -> calibration suite (pytest, recorded) ->
outcomes labeler (golden SQL vs ground truth + readiness bands). Everything
downstream of the pipeline READS the same run — measurements, reliab rigs and
the scoreboard all piggyback on one run per strategy.

Writes ``output/batch/<utc-stamp>/scoreboard.yaml`` and prints the summary.
Strategies run sequentially (one worker, one stack). A failed strategy is
recorded and the batch continues — bugs are a deliverable here, not an abort.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from calibration import outcomes
from calibration import runner as runner_mod

EVAL_ROOT = Path(__file__).resolve().parent.parent


def _run_suite(strategy: str) -> dict[str, Any]:
    """Run the calibration suite for a strategy; return the tail verdict."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "calibration/", "--strategy", strategy, "-q"],
        cwd=EVAL_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tail = (proc.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
    return {"exit_code": proc.returncode, "summary": tail[0]}


def run_batch(strategies: list[str], *, seed: int, skip_generate: bool) -> dict[str, Any]:
    """Run the full matrix; return the scoreboard document."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rows: list[dict[str, Any]] = []

    for strategy in strategies:
        row: dict[str, Any] = {"strategy": strategy}
        try:
            if not skip_generate:
                print(f"[batch] generate {strategy} (seed={seed})", flush=True)
                runner_mod.generate(strategy, seed=seed)
            print(f"[batch] pipeline {strategy} (Temporal + LLM)", flush=True)
            runner_mod.run_pipeline(strategy)
            print(f"[batch] suite {strategy}", flush=True)
            row["suite"] = _run_suite(strategy)
            print(f"[batch] outcomes {strategy}", flush=True)
            row["outcomes"] = outcomes.label(strategy)
        except (Exception, SystemExit) as exc:  # a failed strategy is a finding, not an abort
            row["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[batch] {strategy} FAILED: {row['error']}", flush=True)
        rows.append(row)

    totals = {"right": 0, "wrong_prevented": 0, "wrong_delivered": 0}
    for row in rows:
        for bucket, n in row.get("outcomes", {}).get("buckets", {}).items():
            totals[bucket] += n

    return {
        "batch": stamp,
        "seed": seed,
        "strategies": strategies,
        "scoreboard": totals,
        "runs": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategies", nargs="+", help="strategy names, run in order")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--skip-generate", action="store_true", help="reuse existing data/<strategy>/"
    )
    args = parser.parse_args()

    doc = run_batch(args.strategies, seed=args.seed, skip_generate=args.skip_generate)

    out_dir = EVAL_ROOT / "output" / "batch" / doc["batch"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "scoreboard.yaml"
    out_path.write_text(yaml.safe_dump(doc, sort_keys=False))

    print(f"\n[batch] scoreboard -> {out_path}")
    print(yaml.safe_dump({"scoreboard": doc["scoreboard"]}, sort_keys=False))
    for row in doc["runs"]:
        verdict = row.get("error") or row.get("suite", {}).get("summary", "?")
        buckets = row.get("outcomes", {}).get("buckets", {})
        print(f"  {row['strategy']}: {buckets or '-'} | {verdict}")

    # Exit non-zero only on INFRASTRUCTURE failure (a strategy that errored).
    # Suite reds are data — recorded per row, judged at the regroup, never an
    # abort signal (review wave-1).
    if any("error" in row for row in doc["runs"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
