"""The one calibration runner — run selected strategies in ONE stack lifecycle, build, assert.

Replaces the make generate/pipeline/run/calibrate matrix and the per-strategy churn. The
rules this runner enforces, learned the expensive way:

- **One stack lifecycle.** The docker stack comes up ONCE (idempotent) and stays up for the
  whole run. This runner NEVER does `down -v` — that wipes Temporal's Postgres-backed
  persistence and destabilises it mid-run. Tearing the volume down is an explicit, rare
  `--reset`, never part of a run.
- **Per-strategy workspace isolation.** Each strategy runs in its OWN workspace
  (`workspace_id_for`), so sources never mix — no reset between strategies needed.
- **Orphan-safe.** A `finally` kills any leaked engine worker subprocess. The worker
  normally tears itself down (`worker_running`); this is the crash/interrupt safety net that
  stops leaked workers from piling up and destabilising Temporal.

    uv run python -m calibration.run -s detection-v1,clean      # run these, then assert
    uv run python -m calibration.run --all                      # every strategy
    uv run python -m calibration.run -s detection-v1 --no-assert
    uv run python -m calibration.run --build                    # also (re)build clean bands
    uv run python -m calibration.run --reset                    # the ONLY `down -v`; then exit
    uv run python -m calibration.run --list                     # show strategies

Multi-seed sweeps of one strategy (distinct workspace per seed, for clean bands) stay in
``scripts/sweep_clean_seeds.py`` — that isolation is a different concern from "run these
strategies once each", which is all this runner does.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field

from calibration import runner, stack

WORKER_PROC = "dataraum.worker.main"


def _discover_strategies() -> list[str]:
    return sorted(p.stem for p in runner.STRATEGIES_DIR.glob("*.yaml"))


def _kill_orphan_workers() -> None:
    """Safety net: kill any leaked host engine-worker subprocess (eval-only; cockpit's
    worker runs in docker, not as a host `dataraum.worker.main`)."""
    subprocess.run(["pkill", "-f", WORKER_PROC], check=False)


@dataclass
class Outcome:
    strategy: str
    ran: bool = False
    asserted: bool | None = None  # None = skipped, True = green, False = failed
    error: str = ""


@dataclass
class Summary:
    outcomes: list[Outcome] = field(default_factory=list)

    def ok(self) -> bool:
        return all(o.ran and o.asserted is not False for o in self.outcomes)

    def print(self) -> None:
        print("\n=== calibration run summary ===")
        for o in self.outcomes:
            assert_s = {None: "—", True: "PASS", False: "FAIL"}[o.asserted]
            run_s = "ran" if o.ran else f"ERROR ({o.error})"
            print(f"  {o.strategy:<34} {run_s:<22} assert={assert_s}")
        print(f"  → {'ALL GREEN' if self.ok() else 'FAILURES ABOVE'}")


def _run_one(strategy: str, *, seed: int, fresh: bool, do_assert: bool) -> Outcome:
    out = Outcome(strategy=strategy)
    data_dir = runner.DATA_DIR / strategy
    try:
        if fresh or not data_dir.exists():
            runner.generate(strategy, seed=seed)
        runner.run_pipeline(strategy)  # own workspace; worker up+torn down inside
        out.ran = True
    except Exception as exc:  # noqa: BLE001 — report, keep going to the next strategy
        out.error = f"{type(exc).__name__}: {exc}"
        print(f"[run] {strategy}: FAILED — {out.error}", file=sys.stderr)
        return out

    if do_assert:
        res = subprocess.run(
            ["uv", "run", "pytest", "calibration/", "--strategy", strategy, "-q"],
            cwd=runner.EVAL_ROOT,
        )
        out.asserted = res.returncode == 0
    return out


def run(strategies: list[str], *, seed: int,
        fresh: bool, do_assert: bool, do_build: bool) -> Summary:
    summary = Summary()
    _kill_orphan_workers()      # clear any leftovers from a prior crash before we start
    stack.up()                  # ONCE; idempotent; never `down -v` in this process
    try:
        for strategy in strategies:
            summary.outcomes.append(
                _run_one(strategy, seed=seed, fresh=fresh, do_assert=do_assert)
            )
        if do_build:
            _build_artifacts()
    finally:
        _kill_orphan_workers()  # crash/interrupt safety net; the stack stays UP
    return summary


def _build_artifacts() -> None:
    """Build derived artifacts from completed runs (extend as build steps consolidate here)."""
    print("[build] clean bands")
    subprocess.run(
        ["uv", "run", "python", "scripts/build_clean_bands.py"],
        cwd=runner.EVAL_ROOT, check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-s", "--strategies", help="comma-separated strategy names")
    parser.add_argument("--all", action="store_true", help="run every strategy in strategies/")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fresh", action="store_true", help="regenerate data even if it exists")
    parser.add_argument("--no-assert", action="store_true", help="skip the pytest assertions")
    parser.add_argument("--build", action="store_true", help="(re)build derived artifacts")
    parser.add_argument("--reset", action="store_true",
                        help="tear down the eval stack + volume (the ONLY down -v), then exit")
    parser.add_argument("--list", action="store_true", help="list strategies and exit")
    args = parser.parse_args()

    if args.list:
        print("\n".join(_discover_strategies()))
        return
    if args.reset:
        print("[reset] tearing down the eval stack + volume (down -v)")
        stack.down(volumes=True)
        # A sidecar describes a run in the wiped volume — stale by definition.
        # Leaving it makes _activate_or_skip treat the NEXT batch's not-yet-run
        # strategies as runnable, so their e2e tests read empty workspaces
        # during the first strategy's assert pass (phantom all-missing block).
        for sidecar in runner.OUTPUT_DIR.glob("*/calibration_run.json"):
            sidecar.unlink()
            print(f"[reset] removed stale sidecar {sidecar}")
        return

    if args.all:
        strategies = _discover_strategies()
    elif args.strategies:
        strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    else:
        parser.error("pass -s <names>, --all, or --list")

    known = set(_discover_strategies())
    unknown = [s for s in strategies if s not in known]
    if unknown:
        parser.error(f"unknown strateg"
                     f"{'ies' if len(unknown) > 1 else 'y'}: {', '.join(unknown)}")

    summary = run(
        strategies,
        seed=args.seed,
        fresh=args.fresh,
        do_assert=not args.no_assert,
        do_build=args.build,
    )
    summary.print()
    sys.exit(0 if summary.ok() else 1)


if __name__ == "__main__":
    main()
