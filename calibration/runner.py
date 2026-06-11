"""Drive testdata generation + the dataraum pipeline via Temporal.

Generation runs against ``dataraum-testdata`` directly. The pipeline is a
Temporal workflow now (DAT-344/DAT-370): we bring up Postgres + the Temporal
server (``calibration.stack``), start the engine worker on the host
(``calibration.worker``), and trigger ``addSourceWorkflow`` as a client. A run
ingests a SET of per-file content-keyed sources (DAT-422/DAT-425): each data
file is its own ``src_<digest>`` source, the workflow imports each, fans out a
child workflow per raw table (typing → analytics → ``detect_table``), then runs
``semantic_per_column`` as the session-level reduce. Scores are read back from
Postgres by ``conftest.py``.

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
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

# Load .env (ANTHROPIC_API_KEY etc.) before any module reads it. ``override=True``
# makes this file authoritative over the inherited shell environment — a stale
# exported ANTHROPIC_API_KEY would otherwise shadow the working .env key (load_dotenv
# defaults to override=False) and fail every LLM phase with a 401.
EVAL_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(EVAL_ROOT / ".env", override=True)

from calibration import stack, worker  # noqa: E402
from calibration.stack import up  # noqa: E402

STRATEGIES_DIR = EVAL_ROOT / "strategies"
DATA_DIR = EVAL_ROOT / "data"
OUTPUT_DIR = EVAL_ROOT / "output"

_engine_bootstrapped = False


@dataclass(frozen=True)
class CalibrationRun:
    """Identifiers for a completed pipeline run; persisted to the sidecar.

    ``source_ids`` is the run's per-file content-source set (DAT-422): one
    ``src_<digest>`` source per data file, in upload order.
    """

    strategy: str
    source_ids: tuple[str, ...]
    session_id: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "strategy": self.strategy,
                "source_ids": list(self.source_ids),
                "session_id": self.session_id,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, payload: str) -> CalibrationRun:
        data = json.loads(payload)
        return cls(
            strategy=data["strategy"],
            source_ids=tuple(data["source_ids"]),
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


# Data-file suffixes a source loads. entropy_map.yaml / ground_truth.yaml are
# eval metadata (not source objects), so .yaml is excluded.
_DATA_SUFFIXES = frozenset(
    {".csv", ".tsv", ".parquet", ".json", ".jsonl", ".xlsx", ".db", ".sqlite"}
)

# Declared Source.source_type per suffix. Import dispatches file loads per-URI
# by suffix anyway (only db_recipe consults source_type), so this is metadata,
# mirroring the cockpit's sourceTypeForUri map; unmapped suffixes fall back to
# the generic "file".
_SOURCE_TYPE_BY_SUFFIX = {
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "parquet",
    ".json": "json",
    ".jsonl": "json",
}


@dataclass(frozen=True)
class SourceObject:
    """One uploaded data file = one content-keyed source (DAT-422)."""

    uri: str
    source_name: str  # src_<digest>
    source_type: str


def _content_digest(data: bytes, workspace_id: str) -> str:
    """Workspace-salted SHA-1 content digest of one file's bytes.

    Mirrors the cockpit's ``digestBytes`` small-file path (``upload/digest.ts``):
    SHA-1 over ``bytes + (workspace_id + byte_length)``. Calibration data files
    are far below the cockpit's 8 MB Merkle-roll-up threshold, so the whole-file
    path is the only one needed — identical bytes in the same workspace yield the
    same ``src_<digest>`` source either way (re-upload dedup).
    """
    salted = (workspace_id + str(len(data))).encode()
    return hashlib.sha1(data + salted).hexdigest()


def _upload_sources_to_lake(data_dir: Path, workspace_id: str) -> list[SourceObject]:
    """Upload a strategy's data files to the lake bucket as staged uploads.

    DuckLake is S3-backed (DAT-389): a file source carries ``file_uris`` of
    ``s3://<lake-bucket>/<key>`` objects, not a host path. The dev SeaweedFS S3
    gateway accepts anonymous PUT, so a plain HTTP upload (no boto3, no request
    signing) suffices — and it preserves the bytes exactly, which matters for the
    injected values. Objects land at the locked ``uploads/<digest>/<filename>``
    key (DAT-422, ``upload/policy.ts``): the digest segment is the file's content
    key, so its source is ``src_<digest>`` and its raw table loads as
    ``src_<digest>__<file_stem>``.
    """
    files = sorted(p for p in data_dir.iterdir() if p.suffix.lower() in _DATA_SUFFIXES)
    if not files:
        raise FileNotFoundError(
            f"No source data files ({', '.join(sorted(_DATA_SUFFIXES))}) in {data_dir}"
        )

    objects: list[SourceObject] = []
    for path in files:
        data = path.read_bytes()
        digest = _content_digest(data, workspace_id)
        key = f"uploads/{digest}/{path.name}"
        url = f"http://{stack.S3_ENDPOINT}/{stack.S3_BUCKET}/{key}"
        req = urllib.request.Request(
            url,
            data=data,
            method="PUT",
            headers={"Content-Type": "application/octet-stream"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status not in (200, 201, 204):
                    raise RuntimeError(f"PUT {url} → HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Upload failed for {key}: HTTP {e.code} {e.reason}") from e
        objects.append(
            SourceObject(
                uri=f"s3://{stack.S3_BUCKET}/{key}",
                source_name=f"src_{digest}",
                source_type=_SOURCE_TYPE_BY_SUFFIX.get(path.suffix.lower(), "file"),
            )
        )

    print(f"[eval] Uploaded {len(objects)} file(s) to s3://{stack.S3_BUCKET}/uploads/")
    return objects


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


def _seed_run_sources(
    objects: list[SourceObject],
    *,
    contract: str | None,
    vertical: str | None,
    intent: str,
) -> tuple[str, list[str]]:
    """Upsert one content-keyed Source per object + open an InvestigationSession.

    The run's source set (DAT-422): each uploaded file is its own
    ``src_<digest>`` source carrying exactly one ``file_uris`` entry. Identical
    bytes re-upsert the same row (the name is the content key); the URI is
    refreshed on reuse — the dev SeaweedFS volume is ephemeral, so the bucket is
    recreated and re-uploaded on every run.

    The InvestigationSession row MUST exist before ``addSourceWorkflow`` starts:
    ``typing`` writes ``session_tables`` rows with a NOT-NULL FK to it.

    Returns ``(session_id, source_ids)`` with source_ids in upload order.
    """
    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.investigation.db_models import InvestigationSession
    from dataraum.storage import Source
    from sqlalchemy import select

    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        with workspace_mgr.session_scope() as s:
            source_ids: list[str] = []
            for obj in objects:
                src = s.execute(
                    select(Source).where(Source.name == obj.source_name)
                ).scalar_one_or_none()
                if src is None:
                    src = Source(
                        source_id=str(uuid4()),
                        name=obj.source_name,
                        source_type=obj.source_type,
                        connection_config={"file_uris": [obj.uri]},
                        status="configured",
                    )
                    s.add(src)
                    s.flush()
                else:
                    src.connection_config = {"file_uris": [obj.uri]}
                    s.flush()
                source_ids.append(src.source_id)

            # Source-free since DAT-401: a session composes typed tables (possibly
            # spanning sources), so InvestigationSession carries no source binding.
            # The run's sources ride in AddSourceInput.source_ids instead.
            inv = InvestigationSession(
                session_id=str(uuid4()),
                intent=intent,
                contract=contract,
                vertical=vertical,
                status="active",
            )
            s.add(inv)
            s.flush()
            session_id = inv.session_id
        return session_id, source_ids
    finally:
        workspace_mgr.close()


async def _drive_pipeline(
    *,
    workspace_id: str,
    source_ids: list[str],
    session_id: str,
    vertical: str | None,
    log_path: Path,
) -> tuple[Any, Any]:
    """Trigger ``addSourceWorkflow`` then ``beginSessionWorkflow`` under one worker.

    ``add_source`` ingests the run's source SET (DAT-422): one ``import`` per id
    in ``source_ids``, then types the union and runs the table-local +
    session-level detectors. The identity is source-free — the workflow scopes
    each per-source import itself, so ``source_id`` stays unset here.
    ``begin_session`` then composes the freshly-typed tables into the **same**
    investigation session and runs the cross-table phases (``relationships`` →
    ``semantic_per_table``) plus the terminal relationship ``session_detect`` —
    the only path that scores ``relationship_entropy`` /
    ``join_path_determinism`` (DAT-408). Both run under the same ``session_id``
    so every ``EntropyObjectRecord`` reads back together. The worker is torn
    down when both workflows complete.

    ``operating_model`` then runs the lifecycle spine over the same session —
    resolve → validation (LLM SQL per declared check) → the terminal
    ``operating_model_detect`` (cross_table_consistency: table + column bands,
    DAT-432/L7) → business_cycles → metrics (graph-agent SQL — the product's
    own answer path) → promote.

    Returns ``(AddSourceResult, BeginSessionResult)``.
    """
    from dataraum.worker.contracts import (
        AddSourceInput,
        AddSourceResult,
        BeginSessionInput,
        BeginSessionResult,
        OperatingModelInput,
        OperatingModelResult,
        SessionIdentity,
        SourceIdentity,
        add_source_workflow_id,
        begin_session_workflow_id,
    )

    client = await worker.connect_client()
    source_identity = SourceIdentity(
        workspace_id=workspace_id,
        session_id=session_id,
        vertical=vertical,
    )
    async with worker.worker_running(client, log_path):
        add_result = await client.execute_workflow(
            "addSourceWorkflow",
            AddSourceInput(identity=source_identity, source_ids=source_ids),
            id=add_source_workflow_id(workspace_id, session_id),
            task_queue=stack.TEMPORAL_TASK_QUEUE,
            result_type=AddSourceResult,
            execution_timeout=timedelta(minutes=30),
        )

        typed_table_ids = [t.typed_table_id for t in add_result.tables]
        print(
            f"[eval] beginSessionWorkflow: composing {len(typed_table_ids)} typed "
            f"table(s) into session {session_id}"
        )
        begin_result = await client.execute_workflow(
            "beginSessionWorkflow",
            BeginSessionInput(
                identity=SessionIdentity(workspace_id=workspace_id, session_id=session_id),
                tables=typed_table_ids,
            ),
            id=begin_session_workflow_id(workspace_id, session_id),
            task_queue=stack.TEMPORAL_TASK_QUEUE,
            result_type=BeginSessionResult,
            execution_timeout=timedelta(minutes=30),
        )

        print(
            f"[eval] operatingModelWorkflow: lifecycle spine for session {session_id} "
            f"(validation + detect + cycles + metrics)"
        )
        # Workflow id mirrors the cockpit's convention (workflow-id.ts) — no
        # Python helper exists in contracts.py for this one. An OM failure is a
        # FINDING, not an abort (review wave-1): the expensive add_source +
        # begin_session results above must survive into the sidecar so the
        # detection axes stay readable. 60min timeout: the OM spine is the
        # longest chain (~22 LLM calls) and the activity retry budget must fit
        # inside the workflow's execution window.
        try:
            await client.execute_workflow(
                "operatingModelWorkflow",
                OperatingModelInput(
                    identity=SessionIdentity(workspace_id=workspace_id, session_id=session_id)
                ),
                id=f"operatingmodel-{workspace_id}-{session_id}",
                task_queue=stack.TEMPORAL_TASK_QUEUE,
                result_type=OperatingModelResult,
                execution_timeout=timedelta(minutes=60),
            )
        except Exception as exc:
            print(f"[eval] operatingModelWorkflow FAILED (recorded, run kept): {exc}")
    return add_result, begin_result


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

    from dataraum.server.workspace import get_active_workspace_id

    workspace_id = get_active_workspace_id()

    objects = _upload_sources_to_lake(data_dir, workspace_id)
    session_id, source_ids = _seed_run_sources(
        objects,
        contract=contract,
        vertical=vertical,
        intent=f"calibration:{strategy}",
    )

    output_dir = OUTPUT_DIR / strategy
    output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[eval] Driving addSourceWorkflow + beginSessionWorkflow: "
        f"strategy={strategy} session={session_id} sources={len(source_ids)}"
    )
    add_result, begin_result = asyncio.run(
        _drive_pipeline(
            workspace_id=workspace_id,
            source_ids=source_ids,
            session_id=session_id,
            vertical=vertical,
            log_path=output_dir / "worker.log",
        )
    )
    print(
        f"[eval] addSourceWorkflow complete: {len(add_result.tables)} table(s) processed "
        f"(raw_table_ids={add_result.raw_table_ids})"
    )
    print(
        f"[eval] beginSessionWorkflow complete: {len(begin_result.table_ids)} table(s) in session"
    )

    run = CalibrationRun(
        strategy=strategy,
        source_ids=tuple(source_ids),
        session_id=session_id,
    )
    sidecar_path(strategy).write_text(run.to_json())
    return run


def teach_null_value_and_rerun(
    run: CalibrationRun,
    *,
    values: list[str],
    category: str = "missing_indicators",
    vertical: str | None = "finance",
) -> CalibrationRun:
    """Teach ``values`` as null markers, then RE-RUN the pipeline for the SAME session.

    The DAT-447 teach-closure primitive. Writes one workspace-scoped ``null_value``
    ConfigOverlay row per value, then re-drives addSource+beginSession under the same
    ``session_id``. On the re-run the null_semantics vocabulary witness HITS the taught
    sentinels instead of dissenting, so the pooled conflict on those tokens collapses;
    the re-run promotes a fresh head, so the head-resolved read surface returns the
    dropped score. (Temporal's default ALLOW_DUPLICATE permits re-running a completed
    workflow id with a fresh run_id.)
    """
    bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.server.workspace import get_active_workspace_id
    from dataraum.storage.overlay_models import ConfigOverlay

    workspace_id = get_active_workspace_id()
    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        with workspace_mgr.session_scope() as s:
            for value in values:
                s.add(
                    ConfigOverlay(
                        type="null_value",
                        payload={"category": category, "value": value},
                        session_id=None,  # null_value is workspace-scoped
                    )
                )
    finally:
        workspace_mgr.close()

    output_dir = OUTPUT_DIR / run.strategy
    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[eval] teach null_value {values} (category={category}) → re-run session {run.session_id}"
    )
    asyncio.run(
        _drive_pipeline(
            workspace_id=workspace_id,
            source_ids=list(run.source_ids),
            session_id=run.session_id,
            vertical=vertical,
            log_path=output_dir / "worker_teach_rerun.log",
        )
    )
    return run


def teach_unit_and_rerun(
    run: CalibrationRun,
    *,
    table: str,
    column: str,
    unit: str,
    vertical: str | None = "finance",
) -> CalibrationRun:
    """Teach a column's unit, then RE-RUN the pipeline for the SAME session.

    The column-scoped unit teach (DAT-428): writes one workspace-scoped ``unit``
    ConfigOverlay row ``{table, column, unit}``, then re-drives the pipeline under the
    same ``session_id``. On the re-run ``apply_overlay`` merges the row into
    ``phases/typing.yaml`` ``overrides.units`` and ``typing_phase._apply_unit_overrides``
    patches the column's best TypeCandidate (``detected_unit`` = the taught unit,
    ``unit_confidence`` = 1.0) — the unit now LANDS on an already-typed numeric column
    without having to win a type pattern. ``table`` is the bare name; the reader matches
    it against the source-qualified raw table too.
    """
    bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.server.workspace import get_active_workspace_id
    from dataraum.storage.overlay_models import ConfigOverlay

    workspace_id = get_active_workspace_id()
    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        with workspace_mgr.session_scope() as s:
            s.add(
                ConfigOverlay(
                    type="unit",
                    payload={"table": table, "column": column, "unit": unit},
                    session_id=None,  # unit teach is workspace-scoped
                )
            )
    finally:
        workspace_mgr.close()

    output_dir = OUTPUT_DIR / run.strategy
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[eval] teach unit {table}.{column}={unit} → re-run session {run.session_id}")
    asyncio.run(
        _drive_pipeline(
            workspace_id=workspace_id,
            source_ids=list(run.source_ids),
            session_id=run.session_id,
            vertical=vertical,
            log_path=output_dir / "worker_teach_unit_rerun.log",
        )
    )
    return run


def teach_relationships_and_rerun(
    run: CalibrationRun,
    *,
    verdicts: list[dict[str, str]],
    vertical: str | None = "finance",
) -> CalibrationRun:
    """Write relationship-overlay verdicts, then RE-RUN the pipeline for the SAME session.

    The DAT-447 relationship teach-protocol primitive. Each verdict is
    ``{action, from_table, from_column, to_table, to_column}`` with NAMES (the
    entropy_map's vocabulary); the helper resolves them to this session's column
    ids — the relationship overlay's payload contract
    (``{action, from_column_id, to_column_id}``, see
    ``analysis/relationships/utils.relationship_overlay_pairs``) — writes one
    workspace-scoped ConfigOverlay per verdict, and re-drives the session. On
    the re-run, ``confirm``/``add`` materialize as the ``manual`` witness and
    ``keep`` as ``keeper`` BESIDE the llm rows (the per-(pair, method) dedup),
    so the human witnesses finally vote and the rig can measure them.
    """
    bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.server.workspace import get_active_workspace_id
    from dataraum.storage.overlay_models import ConfigOverlay
    from sqlalchemy import select

    workspace_id = get_active_workspace_id()
    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        with workspace_mgr.session_scope() as s:
            from dataraum.investigation.db_models import SessionTable
            from dataraum.storage import Column, Table

            table_ids = {
                st.table_id
                for st in s.execute(
                    select(SessionTable).where(SessionTable.session_id == run.session_id)
                ).scalars()
            }
            tables = {
                t.table_id: t.table_name
                for t in s.execute(select(Table).where(Table.table_id.in_(table_ids))).scalars()
            }
            # (logical table name, column name) -> column_id, prefix-stripped.
            from calibration.tools._runs import short

            col_ids: dict[tuple[str, str], str] = {}
            for c in s.execute(select(Column).where(Column.table_id.in_(table_ids))).scalars():
                col_ids[(short(tables[c.table_id]), c.column_name)] = c.column_id

            for v in verdicts:
                from_id = col_ids.get((v["from_table"], v["from_column"]))
                to_id = col_ids.get((v["to_table"], v["to_column"]))
                if from_id is None or to_id is None:
                    raise SystemExit(
                        f"verdict names an unknown column: {v} (resolved {from_id}, {to_id})"
                    )
                s.add(
                    ConfigOverlay(
                        type="relationship",
                        payload={
                            "action": v["action"],
                            "from_column_id": from_id,
                            "to_column_id": to_id,
                        },
                        session_id=None,  # workspace-scoped, like the other teach helpers
                    )
                )
    finally:
        workspace_mgr.close()

    output_dir = OUTPUT_DIR / run.strategy
    output_dir.mkdir(parents=True, exist_ok=True)
    actions = ", ".join(f"{v['action']}:{v['from_column']}→{v['to_column']}" for v in verdicts)
    print(f"[eval] teach relationships [{actions}] → re-run session {run.session_id}")
    asyncio.run(
        _drive_pipeline(
            workspace_id=workspace_id,
            source_ids=list(run.source_ids),
            session_id=run.session_id,
            vertical=vertical,
            log_path=output_dir / "worker_teach_relationship_rerun.log",
        )
    )
    return run


def teach_concept_property_and_rerun(
    run: CalibrationRun,
    *,
    concept: str,
    value: str,
    prop: str = "temporal_behavior",
    vertical: str = "finance",
) -> CalibrationRun:
    """Teach a concept-property override, then RE-RUN the pipeline for the SAME session.

    The ontology-property teach (DAT-445 teach-closure for temporal_behavior). Writes
    one workspace-scoped ``concept_property`` ConfigOverlay row
    ``{vertical, concept, property, value}``, then re-drives addSource+beginSession
    under the same ``session_id``. On the re-run ``_apply_concept_property`` patches the
    named concept's ``property`` in ``verticals/<vertical>/ontology.yaml`` and
    ``OntologyLoader`` folds it in, so the ``ontology_prior`` witness now leans the
    taught way: when the taught value matches the LLM's independent stock/flow claim,
    the pooled ``temporal_behavior`` conflict collapses to ε and the re-run's promoted
    head returns the dropped score. ``value`` is the ontology vocabulary
    (``point_in_time`` / ``additive``), NOT the claim vocabulary.
    """
    bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager
    from dataraum.server.workspace import get_active_workspace_id
    from dataraum.storage.overlay_models import ConfigOverlay

    workspace_id = get_active_workspace_id()
    workspace_mgr = ConnectionManager(ConnectionConfig.for_workspace())
    workspace_mgr.initialize()
    try:
        with workspace_mgr.session_scope() as s:
            s.add(
                ConfigOverlay(
                    type="concept_property",
                    payload={
                        "vertical": vertical,
                        "concept": concept,
                        "property": prop,
                        "value": value,
                    },
                    session_id=None,  # concept_property patches the vertical ontology
                )
            )
    finally:
        workspace_mgr.close()

    output_dir = OUTPUT_DIR / run.strategy
    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[eval] teach concept_property {vertical}.{concept}.{prop}={value} "
        f"→ re-run session {run.session_id}"
    )
    asyncio.run(
        _drive_pipeline(
            workspace_id=workspace_id,
            source_ids=list(run.source_ids),
            session_id=run.session_id,
            vertical=vertical,
            log_path=output_dir / "worker_teach_concept_property_rerun.log",
        )
    )
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
