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

from dotenv import load_dotenv

# Load .env before importing pipeline code that reads env vars
EVAL_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(EVAL_ROOT / ".env")

from dataraum.entropy.config import clear_entropy_config_cache  # noqa: E402
from dataraum.pipeline.fixes.interpreters import apply_fix_document  # noqa: E402
from dataraum.pipeline.fixes.models import FixDocument  # noqa: E402
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


def apply_fix_documents(
    fix_docs: list[FixDocument],
    config_root: Path,
) -> None:
    """Apply fix documents to config files in the given root."""
    for doc in fix_docs:
        print(f"[eval] Applying fix: {doc.action} → {doc.table_name}.{doc.column_name}")
        apply_fix_document(doc, config_root=config_root)
    print(f"[eval] Applied {len(fix_docs)} fix(es)")


def run_fix_pipeline(strategy: str) -> None:
    """Re-measure gate scores on fixed output.

    Calls measure_at_gate() directly with the full set of Zone 1 analyses,
    bypassing the scheduler. The scheduler's skip logic marks existing phases
    as SKIPPED which excludes them from _available_analyses() — but we know
    the data is there, so we provide available_analyses explicitly.
    """
    from dataraum.core.config import reset_config_root, set_config_root
    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.entropy.dimensions import AnalysisKey
    from dataraum.entropy.gate import measure_at_gate

    fixed_dir = OUTPUT_DIR / f"{strategy}-fixed"
    if not fixed_dir.exists():
        raise FileNotFoundError(
            f"No fixed output at {fixed_dir}. Run copy_output_for_fixes first."
        )

    # Point config resolution to the fixed output's config directory
    # so detectors read the updated thresholds.yaml with accepted_columns.
    set_config_root(fixed_dir / "config")
    clear_entropy_config_cache()

    # Connect to the fixed output databases
    conn_config = ConnectionConfig.for_directory(fixed_dir)
    manager = ConnectionManager(conn_config)
    manager.initialize()

    try:
        with manager.session_scope() as session:
            from sqlalchemy import select
            from dataraum.storage import Source

            source = session.execute(select(Source)).scalars().first()
            if not source:
                raise RuntimeError("No source found in fixed output DB")

            # All Zone 1 analyses — these phases ran in the original pipeline
            available = {
                AnalysisKey.TYPING,
                AnalysisKey.STATISTICS,
                AnalysisKey.RELATIONSHIPS,
                AnalysisKey.SEMANTIC,
            }

            print(f"[eval] Measuring gate scores: {fixed_dir}")
            gate_result = measure_at_gate(
                session,
                manager._duckdb_conn,  # noqa: SLF001
                source.source_id,
                available,
            )
            print(f"[eval] Gate: {len(gate_result.column_details)} dimensions, "
                  f"{len(gate_result.skipped_detectors)} skipped")

            # Persist gate results to phase_log so conftest can read them
            _persist_gate_to_phase_log(session, source.source_id, gate_result)
            session.commit()
            print("[eval] Gate scores persisted to phase_log")
    finally:
        reset_config_root()
        clear_entropy_config_cache()
        manager.close()


def _persist_gate_to_phase_log(
    session: "Session",
    source_id: str,
    gate_result: "GateResult",
) -> None:
    """Write gate_column_details into the existing quality_review PhaseLog."""
    from sqlalchemy import select

    from dataraum.entropy.detectors.base import get_default_registry
    from dataraum.pipeline.db_models import PhaseLog

    # Build detector_id_map (same as scheduler._persist_gate_scores)
    registry = get_default_registry()
    id_map: dict[str, str] = {}
    for det in registry.get_all_detectors():
        dim_path = f"{det.layer.value}.{det.dimension.value}.{det.sub_dimension.value}"
        id_map[dim_path] = det.detector_id

    outputs = {
        "gate_column_details": gate_result.column_details,
        "detector_id_map": id_map,
    }

    # Update the existing quality_review log (copied from original output)
    existing = session.execute(
        select(PhaseLog)
        .where(PhaseLog.source_id == source_id, PhaseLog.phase_name == "quality_review")
        .order_by(PhaseLog.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if existing is None:
        raise RuntimeError(
            "No quality_review PhaseLog found — cannot persist gate scores"
        )
    existing.outputs = outputs


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run calibration")
    parser.add_argument("strategy", help="Strategy name (e.g. zone1-detection-v1)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--pipeline-only", action="store_true")
    parser.add_argument("--apply-fixes", action="store_true",
                        help="Copy output, apply fixes, re-run pipeline")
    args = parser.parse_args()

    if args.apply_fixes:
        from calibration.fix_specs import PHASE1_FIX_SPECS

        fixed_dir = copy_output_for_fixes(args.strategy)
        config_root = fixed_dir / "config"
        all_docs = [doc for spec in PHASE1_FIX_SPECS for doc in spec.fix_documents]
        apply_fix_documents(all_docs, config_root)
        run_fix_pipeline(args.strategy)
    elif args.pipeline_only:
        run_pipeline(args.strategy)
    elif args.generate_only:
        generate(args.strategy, seed=args.seed)
    else:
        calibration_run(args.strategy, seed=args.seed)
