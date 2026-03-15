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

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from calibration.fix_specs import FixSpec

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


def copy_output_for_fixes(strategy: str) -> Path:
    """Copy pipeline output to an isolated directory for fix application.

    Returns the path to the fixed output directory.
    """
    src = OUTPUT_DIR / strategy
    if not src.exists():
        raise FileNotFoundError(
            f"No pipeline output at {src}. Run pipeline first."
        )
    dst = OUTPUT_DIR / f"{strategy}-fixed"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"[eval] Copied {src} → {dst}")
    return dst


def run_fix_pipeline(strategy: str, fix_specs: list[FixSpec] | None = None) -> None:
    """Apply fixes and re-measure gate scores on fixed output.

    Delegates to ``dataraum.pipeline.fixes.api.apply_fixes`` which handles
    fix application, cascade cleanup, pipeline re-run, and gate persistence.
    """
    if fix_specs is None:
        from calibration.fix_specs import ZONE1_FIX_SPECS

        fix_specs = ZONE1_FIX_SPECS

    from dataraum.pipeline.fixes.api import apply_fixes

    fixed_dir = OUTPUT_DIR / f"{strategy}-fixed"
    if not fixed_dir.exists():
        raise FileNotFoundError(
            f"No fixed output at {fixed_dir}. Run copy_output_for_fixes first."
        )

    all_docs = [d for spec in fix_specs for d in spec.fix_documents]
    data_dir = DATA_DIR / strategy

    result = apply_fixes(
        output_dir=fixed_dir,
        fix_documents=all_docs,
        source_path=data_dir if data_dir.exists() else None,
    )

    if not result.success:
        raise RuntimeError(f"Fix pipeline failed: {result.error}")

    print(
        f"[eval] Applied {len(result.applied_fixes)} fixes, "
        f"phases re-run: {result.phases_rerun}"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run calibration")
    parser.add_argument("strategy", help="Strategy name (e.g. zone1-detection-v1)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--pipeline-only", action="store_true")
    parser.add_argument("--target-phase", default="quality_review",
                        help="Pipeline target phase (default: quality_review, use analysis_review for Zone 2)")
    parser.add_argument("--apply-fixes", action="store_true",
                        help="Copy output, apply fixes, re-measure gate scores")
    args = parser.parse_args()

    if args.apply_fixes:
        copy_output_for_fixes(args.strategy)
        run_fix_pipeline(args.strategy)
    elif args.pipeline_only:
        run_pipeline(args.strategy, target_phase=args.target_phase)
    elif args.generate_only:
        generate(args.strategy, seed=args.seed)
    else:
        calibration_run(args.strategy, seed=args.seed, target_phase=args.target_phase)
