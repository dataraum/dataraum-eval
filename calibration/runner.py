"""Drive testdata generation + the dataraum pipeline via Temporal.

Generation runs against ``dataraum-testdata`` directly. The pipeline is a
Temporal workflow now (DAT-344/DAT-370): we bring up Postgres + the Temporal
server (``calibration.stack``), start the engine worker on the host
(``calibration.worker``), and trigger ``addSourceWorkflow`` as a client. The
workflow imports the source, fans out a child workflow per raw table (typing →
analytics → ``detect_table``), then runs ``semantic_per_column`` as the
source-level reduce. Scores are read back from Postgres by ``conftest.py``.

Usage::

    from calibration.runner import calibration_run
    calibration_run("detection-v1")

Or from the CLI::

    uv run python -m calibration.runner detection-v1
    uv run python -m calibration.runner detection-v1 --generate-only
    uv run python -m calibration.runner detection-v1 --pipeline-only
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

# Load .env (ANTHROPIC_API_KEY etc.) before any module reads it.
EVAL_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(EVAL_ROOT / ".env")

from calibration import stack, worker  # noqa: E402
from calibration.stack import up  # noqa: E402

STRATEGIES_DIR = EVAL_ROOT / "strategies"
DATA_DIR = EVAL_ROOT / "data"
OUTPUT_DIR = EVAL_ROOT / "output"

_engine_bootstrapped = False


@dataclass(frozen=True)
class CalibrationRun:
    """Identifiers for a completed pipeline run; persisted to the sidecar."""

    strategy: str
    source_id: str
    source_name: str
    session_id: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "strategy": self.strategy,
                "source_id": self.source_id,
                "source_name": self.source_name,
                "session_id": self.session_id,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, payload: str) -> CalibrationRun:
        data = json.loads(payload)
        return cls(
            strategy=data["strategy"],
            source_id=data["source_id"],
            source_name=data["source_name"],
            session_id=data["session_id"],
        )


def strategy_path(strategy: str) -> Path:
    path = STRATEGIES_DIR / f"{strategy}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in STRATEGIES_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"Strategy {strategy!r} not found at {path}. Available: {available}"
        )
    return path


def source_name_for(strategy: str) -> str:
    """Stable source name for a strategy (must satisfy [a-z0-9_])."""
    return re.sub(r"[^a-z0-9_]", "_", strategy.lower()).strip("_") or "source"


def sidecar_path(strategy: str) -> Path:
    return OUTPUT_DIR / strategy / "calibration_run.json"


def bootstrap_engine() -> None:
    """Bring up PG + Temporal and materialize the workspace schema.

    The eval process is a Temporal client + Postgres reader: it writes the
    ``Source`` row and reads scores back, so it needs the ``ws_<id>`` schema to
    exist but never opens the DuckLake anchor (that is the host worker's job, in
    its own process). Idempotent within a process; safe from pytest fixtures.
    """
    global _engine_bootstrapped
    if _engine_bootstrapped:
        return

    up()  # docker compose (PG + Temporal) + os.environ setup

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.server.workspace import bootstrap_workspace

    # Activate the workspace (config overlay + active-id pointer) and create the
    # ws_<id> Postgres schema + tables. The worker re-runs this idempotently.
    bootstrap_workspace()

    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    workspace_mgr.close()

    _engine_bootstrapped = True


def generate(
    strategy: str,
    *,
    seed: int = 42,
    months: int | None = None,
    scenario: str = "month-end-close",
    fmt: str = "csv",
) -> Path:
    """Generate test data using a strategy file from this repo."""
    from testdata.scenarios.runner import run_scenario

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


def _create_session_for_source(
    source_name: str,
    source_path: Path,
    *,
    contract: str | None,
    vertical: str | None,
    intent: str,
) -> tuple[str, str]:
    """Find/create the Source + open an InvestigationSession bound to it.

    Returns ``(session_id, source_id)``.
    """
    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.investigation.db_models import InvestigationSession
    from dataraum.storage import Source
    from sqlalchemy import select

    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        with workspace_mgr.session_scope() as s:
            src = s.execute(select(Source).where(Source.name == source_name)).scalar_one_or_none()
            if src is None:
                src = Source(
                    source_id=str(uuid4()),
                    name=source_name,
                    source_type="csv",
                    connection_config={"path": str(source_path.resolve())},
                    status="configured",
                )
                s.add(src)
                s.flush()
            source_id = src.source_id

            inv = InvestigationSession(
                session_id=str(uuid4()),
                source_id=source_id,
                intent=intent,
                contract=contract,
                vertical=vertical,
                status="active",
            )
            s.add(inv)
            s.flush()
            session_id = inv.session_id
        return session_id, source_id
    finally:
        workspace_mgr.close()


async def _drive_add_source(
    *,
    strategy: str,
    workspace_id: str,
    source_id: str,
    session_id: str,
    vertical: str | None,
    log_path: Path,
) -> Any:
    """Trigger ``addSourceWorkflow`` under a freshly-started host worker.

    Returns the workflow's :class:`AddSourceResult` (raw table ids + per-table
    raw→typed outcomes). The worker is torn down when the workflow completes.
    """
    from dataraum.worker.contracts import AddSourceInput, AddSourceResult, SourceIdentity

    client = await worker.connect_client()
    identity = SourceIdentity(
        workspace_id=workspace_id,
        source_id=source_id,
        session_id=session_id,
        vertical=vertical,
    )
    async with worker.worker_running(client, log_path):
        return await client.execute_workflow(
            "addSourceWorkflow",
            AddSourceInput(identity=identity),
            id=f"calibration-{strategy}-{session_id}",
            task_queue=stack.TEMPORAL_TASK_QUEUE,
            result_type=AddSourceResult,
            execution_timeout=timedelta(minutes=30),
        )


def run_pipeline(
    strategy: str,
    *,
    contract: str | None = "aggregation_safe",
    vertical: str | None = "finance",
) -> CalibrationRun:
    """Run the pipeline against generated data in-process. Persists sidecar.

    Returns the identifiers needed to read scores back from Postgres.
    """
    data_dir = DATA_DIR / strategy
    if not data_dir.exists():
        raise FileNotFoundError(f"No test data at {data_dir}. Run generate({strategy!r}) first.")

    bootstrap_engine()

    source_name = source_name_for(strategy)
    session_id, source_id = _create_session_for_source(
        source_name,
        data_dir,
        contract=contract,
        vertical=vertical,
        intent=f"calibration:{strategy}",
    )

    output_dir = OUTPUT_DIR / strategy
    output_dir.mkdir(parents=True, exist_ok=True)

    from dataraum.server.workspace import get_active_workspace_id

    workspace_id = get_active_workspace_id()

    print(f"[eval] Driving addSourceWorkflow: strategy={strategy} session={session_id}")
    result = asyncio.run(
        _drive_add_source(
            strategy=strategy,
            workspace_id=workspace_id,
            source_id=source_id,
            session_id=session_id,
            vertical=vertical,
            log_path=output_dir / "worker.log",
        )
    )
    print(
        f"[eval] addSourceWorkflow complete: {len(result.tables)} table(s) processed "
        f"(raw_table_ids={result.raw_table_ids})"
    )

    run = CalibrationRun(
        strategy=strategy,
        source_id=source_id,
        source_name=source_name,
        session_id=session_id,
    )
    sidecar_path(strategy).write_text(run.to_json())
    return run


def calibration_run(
    strategy: str,
    *,
    seed: int = 42,
    months: int | None = None,
    scenario: str = "month-end-close",
    contract: str | None = "aggregation_safe",
    vertical: str | None = "finance",
) -> CalibrationRun:
    """Full calibration run: generate test data + run the pipeline in-process."""
    generate(strategy, seed=seed, months=months, scenario=scenario)
    return run_pipeline(strategy, contract=contract, vertical=vertical)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run calibration")
    parser.add_argument("strategy", help="Strategy name (e.g. detection-v1)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--pipeline-only", action="store_true")
    parser.add_argument("--contract", default="aggregation_safe")
    parser.add_argument(
        "--vertical",
        default="finance",
        help="Domain vertical (default: finance). Pass empty string for cold start.",
    )
    args = parser.parse_args()

    vertical = args.vertical or None

    if args.pipeline_only:
        run_pipeline(args.strategy, contract=args.contract, vertical=vertical)
    elif args.generate_only:
        generate(args.strategy, seed=args.seed)
    else:
        calibration_run(args.strategy, seed=args.seed, contract=args.contract, vertical=vertical)
