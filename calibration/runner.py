"""Orchestrates testdata generation and pipeline execution for calibration runs.

Uses direct Python API calls to dataraum-testdata and dataraum-context
(installed as editable dependencies from vendor/).

Usage from pytest (via conftest fixtures) or directly:

    from calibration.runner import generate, run_pipeline, calibration_run

    # Generate test data using a strategy owned by this repo
    generate("zone1-detection-v1", seed=42)

    # Run the pipeline on generated data
    run_pipeline("zone1-detection-v1")

    # Or do both in one call
    calibration_run("zone1-detection-v1", seed=42)
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing pipeline code that reads env vars
EVAL_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(EVAL_ROOT / ".env")

from dataraum.pipeline.runner import GateMode, RunConfig, RunResult  # noqa: E402
from dataraum.pipeline.runner import run as pipeline_run  # noqa: E402
from testdata.scenarios.runner import run_scenario  # noqa: E402

STRATEGIES_DIR = EVAL_ROOT / "strategies"
DATA_DIR = EVAL_ROOT / "data"
OUTPUT_DIR = EVAL_ROOT / "output"


def strategy_path(strategy: str) -> Path:
    """Resolve a strategy name to its YAML file path."""
    path = STRATEGIES_DIR / f"{strategy}.yaml"
    if not path.exists():
        available = [p.stem for p in STRATEGIES_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"Strategy {strategy!r} not found at {path}. "
            f"Available: {available}"
        )
    return path


def generate(
    strategy: str,
    *,
    seed: int = 42,
    months: int | None = None,
    scenario: str = "month-end-close",
    fmt: str = "csv",
) -> Path:
    """Generate test data using a strategy file from this repo.

    Returns the output data directory.
    """
    sf = strategy_path(strategy)
    data_dir = DATA_DIR / strategy
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"[eval] Generating: strategy={strategy} seed={seed} scenario={scenario}")
    run_scenario(
        scenario,
        strategy_file=sf,
        seed=seed,
        months=months,
        output_dir=data_dir,
        fmt=fmt,
    )
    print(f"[eval] Data written to {data_dir}")
    return data_dir


def run_pipeline(
    strategy: str,
    *,
    target_phase: str = "quality_review",
    gate_mode: GateMode = GateMode.SKIP,
    contract: str | None = "aggregation_safe",
) -> RunResult:
    """Run the dataraum pipeline on generated test data.

    Returns RunResult with pipeline output.
    """
    data_dir = DATA_DIR / strategy
    if not data_dir.exists():
        raise FileNotFoundError(
            f"No test data at {data_dir}. Run generate('{strategy}') first."
        )

    output_dir = OUTPUT_DIR / strategy
    output_dir.mkdir(parents=True, exist_ok=True)

    config = RunConfig(
        source_path=data_dir,
        output_dir=output_dir,
        target_phase=target_phase,
        gate_mode=gate_mode,
        contract=contract,
    )

    print(f"[eval] Running pipeline: data={data_dir} output={output_dir}")
    result = pipeline_run(config)
    run_result = result.unwrap()
    print(f"[eval] Pipeline {'succeeded' if run_result.success else 'FAILED'}: {output_dir}")
    return run_result


def calibration_run(
    strategy: str,
    *,
    seed: int = 42,
    months: int | None = None,
    scenario: str = "month-end-close",
    target_phase: str = "quality_review",
    gate_mode: GateMode = GateMode.SKIP,
    contract: str | None = "aggregation_safe",
) -> dict[str, Path | RunResult]:
    """Full calibration run: generate test data + run pipeline.

    Returns dict with 'data_dir', 'output_dir', and 'run_result'.
    """
    data_dir = generate(strategy, seed=seed, months=months, scenario=scenario)
    run_result = run_pipeline(
        strategy,
        target_phase=target_phase,
        gate_mode=gate_mode,
        contract=contract,
    )
    return {
        "data_dir": data_dir,
        "output_dir": OUTPUT_DIR / strategy,
        "run_result": run_result,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run calibration")
    parser.add_argument("strategy", help="Strategy name (e.g. zone1-detection-v1)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--pipeline-only", action="store_true")
    args = parser.parse_args()

    if args.pipeline_only:
        run_pipeline(args.strategy)
    elif args.generate_only:
        generate(args.strategy, seed=args.seed)
    else:
        calibration_run(args.strategy, seed=args.seed)
