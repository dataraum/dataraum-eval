"""Run the engine Temporal worker on the host + drive ``addSourceWorkflow``.

The engine is a Temporal activity worker (DAT-344/DAT-370): a pipeline run is a
workflow, not an in-process function call. Calibration drives one by

1. starting the worker as a **host subprocess** (``python -m dataraum.worker.main``
   on the eval interpreter, so it runs the live working-tree engine and reads
   the host ``data/`` + ``lake_data/`` dirs directly), and
2. acting as a Temporal **client**: triggering ``addSourceWorkflow`` and awaiting
   its :class:`AddSourceResult`.

The worker bootstraps its own substrate (DuckLake anchor + workspace) in its own
process; the eval process only needs Postgres for the ``Source`` row and the
score read-back, so the two never share the process-global DuckLake anchor.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import temporalio.api.enums.v1 as temporal_enums
import temporalio.api.taskqueue.v1 as temporal_taskqueue
import temporalio.api.workflowservice.v1 as temporal_workflowservice
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from calibration import stack

EVAL_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = EVAL_ROOT / "vendor" / "dataraum-context" / "packages" / "engine"

# Generous: the worker opens the DuckLake anchor + materializes the ws_<id>
# schema before it advertises itself as polling. Cold first boot is the slow case.
_POLL_READY_TIMEOUT = 120.0
_SHUTDOWN_TIMEOUT = 30.0


async def connect_client() -> Client:
    """Connect a Temporal client to the stack server, with a short connect retry.

    Uses the Pydantic data converter — the workflow I/O contracts
    (``AddSourceInput`` / ``AddSourceResult``) are Pydantic models.
    """
    deadline = time.monotonic() + 30.0
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return await Client.connect(
                stack.TEMPORAL_HOST,
                namespace=stack.TEMPORAL_NAMESPACE,
                data_converter=pydantic_data_converter,
            )
        except Exception as err:  # noqa: BLE001 — server may still be coming up
            last_err = err
            await asyncio.sleep(1.0)
    raise RuntimeError(f"Could not connect to Temporal at {stack.TEMPORAL_HOST}: {last_err}")


async def _wait_until_polling(client: Client, proc: subprocess.Popen[bytes], log_path: Path) -> None:
    """Block until the worker is polling the task queue (or it dies / times out)."""
    request = temporal_workflowservice.DescribeTaskQueueRequest(
        namespace=stack.TEMPORAL_NAMESPACE,
        task_queue=temporal_taskqueue.TaskQueue(name=stack.TEMPORAL_TASK_QUEUE),
        task_queue_type=temporal_enums.TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
    )
    deadline = time.monotonic() + _POLL_READY_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"Engine worker exited early (rc={proc.returncode}) before polling. "
                f"Last log lines:\n{_log_tail(log_path)}"
            )
        try:
            resp = await client.workflow_service.describe_task_queue(request)
            if resp.pollers:
                return
        except Exception:  # noqa: BLE001, S110 — task queue not registered yet
            pass
        await asyncio.sleep(1.0)
    raise TimeoutError(
        f"Engine worker did not start polling {stack.TEMPORAL_TASK_QUEUE!r} within "
        f"{_POLL_READY_TIMEOUT:.0f}s. Last log lines:\n{_log_tail(log_path)}"
    )


def _log_tail(log_path: Path, lines: int = 40) -> str:
    if not log_path.exists():
        return "(no worker log)"
    return "\n".join(log_path.read_text().splitlines()[-lines:])


@asynccontextmanager
async def worker_running(client: Client, log_path: Path) -> AsyncIterator[None]:
    """Start the engine worker subprocess; tear it down on exit.

    Inherits the calibration env (substrate + Temporal + workspace, all set by
    :func:`calibration.stack.up`). Worker stdout/stderr is teed to ``log_path``
    so a boot failure surfaces in the readiness error.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "dataraum.worker.main"],
            cwd=str(ENGINE_DIR),
            env=os.environ.copy(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            print(f"[worker] Starting engine worker (pid={proc.pid}); log → {log_path}")
            await _wait_until_polling(client, proc, log_path)
            print(f"[worker] Polling {stack.TEMPORAL_TASK_QUEUE!r} — ready.")
            yield
        finally:
            _terminate(proc)


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Stop the worker gracefully (SIGINT → substrate teardown), then hard-kill."""
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=_SHUTDOWN_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    print("[worker] Engine worker stopped.")
