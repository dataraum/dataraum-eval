"""Drive testdata generation + the dataraum pipeline via HTTP MCP.

Generation still runs in-process against ``dataraum-testdata`` (no remote
surface there). The pipeline runs in the control-plane container; the runner
talks to it through the MCP tool surface (add_source → begin_session →
measure).

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
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env before importing testdata (reads env vars at import time).
EVAL_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(EVAL_ROOT / ".env")

from testdata.scenarios.runner import run_scenario  # noqa: E402

from calibration.mcp_client import call_tool, mcp_session  # noqa: E402
from calibration.stack import (  # noqa: E402
    DATA_DIR,
    StackHandle,
    container_path_for,
    up,
)

STRATEGIES_DIR = EVAL_ROOT / "strategies"
OUTPUT_DIR = EVAL_ROOT / "output"

# Polling cadence while the pipeline is running.
_PIPELINE_POLL_INTERVAL = 5.0
_PIPELINE_POLL_TIMEOUT = 30 * 60  # 30 min hard cap


def strategy_path(strategy: str) -> Path:
    path = STRATEGIES_DIR / f"{strategy}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in STRATEGIES_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"Strategy {strategy!r} not found at {path}. Available: {available}"
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
    """Generate test data using a strategy file from this repo."""
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


def _source_name(strategy: str) -> str:
    """Strategy name → MCP source name (lowercase, a-z/0-9/_)."""
    return strategy.replace("-", "_")


async def _ensure_source_registered(session: Any, name: str, path: str) -> None:
    """Idempotent add_source — skip if already present, error on anything else.

    Caller must ensure no session is active (add_source refuses with "Sources
    are sealed" while a session holds the workspace).
    """
    listing = await call_tool(session, "list_sources", {})
    if any(s.get("name") == name for s in listing.get("sources", [])):
        return
    result = await call_tool(session, "add_source", {"name": name, "path": path})
    if "error" in result:
        raise RuntimeError(f"add_source({name!r}, {path!r}) failed: {result}")


async def _end_active_session_if_any(session: Any) -> None:
    """Best-effort: end whatever session is active so add_source/begin_session can proceed.

    Tolerates the "no active session" case — that's the desired state.
    """
    result = await call_tool(session, "end_session", {"outcome": "abandoned"})
    err = str(result.get("error", "")).lower()
    if "error" in result and "no active" not in err and "no session" not in err:
        # Anything else (a real failure) — let the next call surface it; we
        # don't want to mask a transport problem here.
        pass


async def setup_strategy(
    session: Any,
    strategy: str,
    *,
    contract: str | None = "aggregation_safe",
    vertical: str | None = "finance",
) -> dict[str, Any]:
    """Idempotent: end → register → begin a session bound to ``strategy``'s source.

    Returns the begin_session response. Safe to call repeatedly across
    strategies in a single MCP session.
    """
    name = _source_name(strategy)
    container_path = container_path_for(strategy)
    await _end_active_session_if_any(session)
    await _ensure_source_registered(session, name, container_path)
    args: dict[str, Any] = {"source": name, "intent": f"calibration:{strategy}"}
    if contract:
        args["contract"] = contract
    if vertical:
        args["vertical"] = vertical
    begin = await call_tool(session, "begin_session", args)
    if "error" in begin:
        raise RuntimeError(f"begin_session({name!r}) failed: {begin}")
    return begin


async def _wait_for_pipeline(session: Any) -> dict[str, Any]:
    """Poll measure() until the pipeline finishes; return the final response."""
    start = time.monotonic()
    while True:
        resp = await call_tool(session, "measure", {})
        status = resp.get("status") or resp.get("pipeline_status")
        if status in ("complete", "ready"):
            return resp
        if status == "failed":
            raise RuntimeError(f"Pipeline failed: {resp}")
        if time.monotonic() - start > _PIPELINE_POLL_TIMEOUT:
            raise TimeoutError(
                f"Pipeline did not complete within {_PIPELINE_POLL_TIMEOUT}s. Last: {resp}"
            )
        phases = resp.get("phases_completed", [])
        print(f"[eval] pipeline status={status} phases_completed={len(phases)}")
        await asyncio.sleep(_PIPELINE_POLL_INTERVAL)


async def _run_pipeline_async(
    handle: StackHandle,
    strategy: str,
    *,
    contract: str | None,
    vertical: str | None,
) -> dict[str, Any]:
    async with mcp_session(handle) as s:
        begin = await setup_strategy(s, strategy, contract=contract, vertical=vertical)
        print(f"[eval] begin_session ok: has_pipeline_data={begin.get('has_pipeline_data')}")
        final = await _wait_for_pipeline(s)
        print(
            f"[eval] pipeline complete: points={len(final.get('points', []))} "
            f"phases={len(final.get('phases_completed', []))}"
        )
        return final


def run_pipeline(
    strategy: str,
    *,
    contract: str | None = "aggregation_safe",
    vertical: str | None = "finance",
) -> dict[str, Any]:
    """Run the pipeline against test data via MCP. Returns the final measure() response."""
    data_dir = DATA_DIR / strategy
    if not data_dir.exists():
        raise FileNotFoundError(
            f"No test data at {data_dir}. Run generate({strategy!r}) first."
        )

    handle = up()
    print(f"[eval] Running pipeline via MCP: strategy={strategy}")
    return asyncio.run(_run_pipeline_async(handle, strategy, contract=contract, vertical=vertical))


def calibration_run(
    strategy: str,
    *,
    seed: int = 42,
    months: int | None = None,
    scenario: str = "month-end-close",
    contract: str | None = "aggregation_safe",
    vertical: str | None = "finance",
) -> dict[str, Any]:
    """Full calibration run: generate test data + drive the pipeline via MCP."""
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
