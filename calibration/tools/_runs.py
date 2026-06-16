"""Shared bootstrap for the read-only calibration tools.

Loads the run sidecar WITHOUT the conftest's run-if-missing behavior — a read
tool must never kick a pipeline — and hands out a workspace session over the
live eval stack.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from calibration import runner as runner_mod
from calibration.runner import CalibrationRun


def load_run(strategy: str) -> CalibrationRun:
    """Return the completed run's identifiers; exit loudly when there is none.

    Activates ``strategy``'s OWN workspace (DAT-508) so the ``workspace_session``
    that follows resolves the right ``ws_<id>`` schema — each strategy is its own
    workspace now that sessions are gone.
    """
    sidecar = runner_mod.sidecar_path(strategy)
    if not sidecar.exists():
        raise SystemExit(
            f"no completed run for {strategy!r} (missing {sidecar}) — run the pipeline first: "
            f"uv run python -m calibration.runner {strategy}"
        )
    runner_mod.activate_workspace(strategy)
    return CalibrationRun.from_json(sidecar.read_text())


def short(name: str) -> str:
    """Strip the ``src_<digest>__`` upload prefix off a table name."""
    return name.split("__", 1)[1] if "__" in name else name


@contextmanager
def workspace_session() -> Generator[Any]:
    """A SQLAlchemy session on the eval workspace schema (engine bootstrapped)."""
    runner_mod.bootstrap_engine()

    from dataraum.core.connections import ConnectionConfig, ConnectionManager

    manager = ConnectionManager(ConnectionConfig.for_workspace())
    manager.initialize()
    try:
        with manager.session_scope() as session:
            yield session
    finally:
        manager.close()
