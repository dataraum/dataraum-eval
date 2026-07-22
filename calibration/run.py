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
    uv run python -m calibration.run --all                      # every synthetic strategy
    uv run python -m calibration.run -s rel-f1                  # a WILD corpus: stage→frame→run→scoreboard
    uv run python -m calibration.run -s detection-v1 --no-assert
    uv run python -m calibration.run --build                    # also (re)build clean bands
    uv run python -m calibration.run --reset                    # the ONLY `down -v`; then exit
    uv run python -m calibration.run --list                     # show strategies + wild corpora

A target is a synthetic strategy (``strategies/<name>.yaml`` — recall assertable) OR a
wild corpus (registered in ``calibration/corpus_registry.yaml`` / staged / stageable). The wild
lane skips generate, frames the corpus's vertical, runs the pipeline, and grades with
the fire-rate scoreboard (recall stands down — a wild corpus has no injected truth).

Multi-seed sweeps of one strategy (distinct workspace per seed, for clean bands) stay in
``scripts/sweep_clean_seeds.py`` — that isolation is a different concern from "run these
strategies once each", which is all this runner does.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from calibration import corpora, runner, stack

WORKER_PROC = "dataraum.worker.main"


def _discover_strategies() -> list[str]:
    return sorted(p.stem for p in runner.STRATEGIES_DIR.glob("*.yaml"))


def _staged_wild(name: str) -> bool:
    """A wild corpus already staged into ``data/<name>/`` (tier: wild truth present)."""
    import yaml

    truth = runner.DATA_DIR / name / "metadata_truth.yaml"
    if not truth.exists():
        return False
    try:
        return str((yaml.safe_load(truth.read_text()) or {}).get("tier") or "").lower() == "wild"
    except (OSError, ValueError):
        return False


def _stageable_wild(name: str) -> bool:
    """A wild corpus fetched under ``corpora/relbench/<name>/`` but not yet staged."""
    return (runner.EVAL_ROOT / "corpora" / "relbench" / name / "schema.json").exists()


def _is_wild_target(name: str) -> bool:
    """Route ``name`` to the wild lane? A finance strategy always wins the name.

    Wild = registered in ``calibration/corpus_registry.yaml``, already staged with ``tier: wild``,
    or fetched-and-stageable under ``corpora/``. The synthetic backbone is never wild.
    """
    if name in set(_discover_strategies()):
        return False
    return corpora.get(name) is not None or _staged_wild(name) or _stageable_wild(name)


def _llm_call_count(name: str) -> int | None:
    """Cost proxy: the run's dumped prompt+response artifacts (one file per LLM call).

    The provider chokepoint dumps every rendered prompt + raw response under
    ``output/<name>/prompts/`` (runner.activate_workspace sets PROMPT_DUMP_DIR). Counting
    them is the honest "what did this run cost in LLM calls" line — a run that spends
    tokens is accountable for how many. ``None`` when nothing was dumped."""
    prompts = runner.OUTPUT_DIR / name / "prompts"
    if not prompts.is_dir():
        return None
    return sum(1 for _ in prompts.rglob("*") if _.is_file())


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
    tier: str = "synthetic"  # synthetic (recall assertable) | wild (scoreboard only)
    # oracle_coverage.json, written by conftest.pytest_terminal_summary
    coverage: dict[str, Any] = field(default_factory=dict)
    # the wild fire-rate scoreboard's findings (mute/never-fired/saturated), if produced
    scoreboard: dict[str, Any] = field(default_factory=dict)
    llm_calls: int | None = None  # dumped prompt+response artifacts — the cost proxy


def _read_coverage(strategy: str) -> dict[str, Any]:
    """What the assert pass actually graded (see conftest.pytest_terminal_summary)."""
    path = runner.OUTPUT_DIR / strategy / "oracle_coverage.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return {}


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
            cov = o.coverage
            graded_s = ""
            if cov:
                graded_s = (
                    f"  graded={cov.get('passed', 0) + cov.get('failed', 0)}"
                    f" skipped={cov.get('skipped', 0)}"
                    f" xfail={cov.get('xfailed', 0)}"
                )
                if cov.get("xpassed"):
                    graded_s += f" XPASS={cov['xpassed']}"
            # Cost line: tier + LLM-call count, so every run is accountable for its spend.
            cost_s = f"  [{o.tier}"
            if o.llm_calls is not None:
                cost_s += f", {o.llm_calls} llm-calls"
            cost_s += "]"
            print(f"  {o.strategy:<34} {run_s:<22} assert={assert_s}{cost_s}{graded_s}")

        # Skips are how a run goes green without checking anything — name the ORACLES
        # (nodeids), not just reason tallies, so a silently-dropped one is visible.
        for o in self.outcomes:
            ledger = o.coverage.get("oracles") or {}
            skipped = [
                (nid, e.get("reason", ""))
                for nid, e in ledger.items()
                if e.get("status") == "skipped"
            ]
            if skipped:
                print(f"\n  {o.strategy} — skipped oracles ({len(skipped)}):")
                for nid, reason in skipped[:12]:
                    print(f"    - {nid.split('::', 1)[-1]:<46} {reason[:68]}")
                if len(skipped) > 12:
                    print(
                        f"    … {len(skipped) - 12} more "
                        f"(see output/{o.strategy}/oracle_coverage.json)"
                    )
                continue
            # Fallback: coverage files written before the per-oracle ledger existed.
            reasons = o.coverage.get("skip_reasons") or {}
            if not reasons:
                continue
            print(f"\n  {o.strategy} — skipped oracles ({o.coverage.get('skipped', 0)}):")
            for reason, count in list(reasons.items())[:8]:
                print(f"    {count:>3}× {reason[:110]}")
            if len(reasons) > 8:
                print(f"    … {len(reasons) - 8} more distinct reason(s)")

        # Coverage regressions — oracles that graded in the blessed baseline and
        # stood down now. A FINDING TO TRIAGE, never an automatic engine-blame: the
        # oracle may be wrongly skipping (test-suite/stale-eval bug), the engine may
        # have stopped producing what it grades (engine bug), or the baseline was
        # blessed at a bad state. The diff surfaces it; a human decides which, and it
        # never fails the run.
        from calibration import coverage

        for o in self.outcomes:
            ledger = o.coverage.get("oracles") or {}
            base = coverage.load_baseline(o.strategy)
            if base is None or not ledger:
                continue
            regressed = coverage.diff_against_baseline(base, ledger)["regressed"]
            if not regressed:
                continue
            print(
                f"\n  ⚠ {o.strategy} — COVERAGE REGRESSION "
                f"({len(regressed)} graded in baseline, not now):"
            )
            for nid in regressed[:12]:
                print(f"    - {nid.split('::', 1)[-1]}")
            if len(regressed) > 12:
                print(f"    … {len(regressed) - 12} more")
            print(
                "    triage: oracle wrongly skipping (test-suite/stale-eval bug) · "
                "engine stopped producing it (engine bug) · baseline blessed wrong · "
                "re-bless: python -m calibration.run -s <strat> --bless-coverage"
            )

        # Wild scoreboard findings — on a wild corpus recall stands down, so the
        # fire-rate flags ARE the grade. A miserable result is a finding to file
        # (charter), never an auto engine-blame. The full board printed inline above.
        for o in self.outcomes:
            sb = o.scoreboard
            if not sb:
                continue
            flags = []
            if sb.get("mute"):
                flags.append(f"MUTE: {', '.join(sb['mute'])}")
            if sb.get("never_fired"):
                flags.append(f"NEVER-FIRED: {', '.join(sb['never_fired'])}")
            if sb.get("saturated"):
                flags.append(f"SATURATED: {', '.join(sb['saturated'])}")
            head = f"\n  {o.strategy} — wild scoreboard: "
            print(head + ("; ".join(flags) if flags else "no flags (read the distribution)"))
            if flags:
                print("    → triage each: a confirmed miss/over-fire is a filed Finding, "
                      "not an engine patch (calibration/findings.py)")

        print(f"\n  → {'ALL GREEN' if self.ok() else 'FAILURES ABOVE'}")


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
        out.coverage = _read_coverage(strategy)
    out.llm_calls = _llm_call_count(strategy)
    return out


def _ensure_wild_staged(name: str) -> None:
    """Stage the corpus into ``data/<name>/`` if it isn't already (fetch stays manual)."""
    if _staged_wild(name):
        return
    if not _stageable_wild(name):
        raise FileNotFoundError(
            f"{name} is not staged (no data/{name}/metadata_truth.yaml) and not stageable "
            f"(no corpora/relbench/{name}/). Fetch it, then: "
            f"uv run python scripts/stage_wild_corpus.py {name}"
        )
    subprocess.run(
        ["uv", "run", "python", "scripts/stage_wild_corpus.py", name],
        cwd=runner.EVAL_ROOT, check=True,
    )


def _frame_wild(name: str) -> None:
    """Write the corpus's vertical (concept vocabulary) into its workspace before the run.

    A corpus in a domain the engine hasn't been framed for cannot reach the pipeline at
    all (semantic_per_column fails on ``_adhoc``); this is eval's stand-in for the cockpit
    frame stage. Runs as a subprocess so it activates its own workspace cleanly; the
    concepts persist in Postgres for the in-process pipeline to read.
    """
    res = subprocess.run(
        ["uv", "run", "python", "scripts/frame_wild_vertical.py", name],
        cwd=runner.EVAL_ROOT,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"framing {name} failed — likely no vertical declared for it "
            f"(scripts/frame_wild_vertical.py VERTICALS). A wild corpus with no frame "
            f"cannot reach the pipeline; declare its concepts or file the gap."
        )


def _emit_scoreboard(name: str, out: Outcome) -> None:
    """Build + print + persist the wild fire-rate scoreboard — the frontier grade.

    Always runs for a wild corpus, even with ``--no-assert``: on wild data recall is
    unassertable, so the scoreboard IS the grade (a detector that found nothing is only
    visible here). Best-effort — a scoreboard failure never sinks the run.
    """
    from calibration import scoreboard

    try:
        board = scoreboard.load_scoreboard(name)
    except Exception as exc:  # noqa: BLE001 — the scoreboard is a report, not a gate
        print(f"[scoreboard] {name}: could not build — {exc}", file=sys.stderr)
        return
    print("\n" + scoreboard.render(board, is_wild=True))
    print(f"\n  → {scoreboard.write_scoreboard(board).relative_to(runner.EVAL_ROOT)}")
    out.scoreboard = {
        "mute": board.mute,
        "never_fired": board.never_fired,
        "saturated": board.saturated,
    }


def _run_one_wild(name: str, *, do_assert: bool) -> Outcome:
    """Stage → frame → run the pipeline → grade (wild-aware oracles) → scoreboard.

    The frontier lane: no generate (the data is real), the vertical is framed not
    injected, recall is unassertable (wild oracles stand down), and the fire-rate
    scoreboard is the grade.
    """
    out = Outcome(strategy=name, tier="wild")
    try:
        _ensure_wild_staged(name)
        _frame_wild(name)
        spec = corpora.get(name)
        vertical = spec.vertical if spec else name  # defaults to the corpus name
        runner.run_pipeline(name, vertical=vertical)
        out.ran = True
    except Exception as exc:  # noqa: BLE001 — report, keep going to the next target
        out.error = f"{type(exc).__name__}: {exc}"
        print(f"[run] {name} (wild): FAILED — {out.error}", file=sys.stderr)
        return out

    if do_assert:
        res = subprocess.run(
            ["uv", "run", "pytest", "calibration/", "--strategy", name, "-q"],
            cwd=runner.EVAL_ROOT,
        )
        out.asserted = res.returncode == 0
        out.coverage = _read_coverage(name)
    _emit_scoreboard(name, out)
    out.llm_calls = _llm_call_count(name)
    return out


def _dispatch(strategy: str, *, seed: int, fresh: bool, do_assert: bool) -> Outcome:
    """Route a target to the wild lane or the synthetic lane."""
    if _is_wild_target(strategy):
        return _run_one_wild(strategy, do_assert=do_assert)
    return _run_one(strategy, seed=seed, fresh=fresh, do_assert=do_assert)


def run(strategies: list[str], *, seed: int,
        fresh: bool, do_assert: bool, do_build: bool) -> Summary:
    summary = Summary()
    _kill_orphan_workers()      # clear any leftovers from a prior crash before we start
    stack.up()                  # ONCE; idempotent; never `down -v` in this process
    try:
        for strategy in strategies:
            summary.outcomes.append(
                _dispatch(strategy, seed=seed, fresh=fresh, do_assert=do_assert)
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
    parser.add_argument("--all", action="store_true",
                        help="run every synthetic strategy in strategies/ (wild corpora are "
                             "opt-in by name — they cost LLM tokens; see --list)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fresh", action="store_true", help="regenerate data even if it exists")
    parser.add_argument("--no-assert", action="store_true", help="skip the pytest assertions")
    parser.add_argument("--build", action="store_true", help="(re)build derived artifacts")
    parser.add_argument("--reset", action="store_true",
                        help="tear down the eval stack + volume (the ONLY down -v), then exit")
    parser.add_argument("--list", action="store_true", help="list strategies and exit")
    parser.add_argument(
        "--bless-coverage", action="store_true",
        help="write the selected strategies' current oracle_coverage as the committed "
             "baseline, then exit (the graded set future runs diff against)",
    )
    args = parser.parse_args()

    if args.list:
        print("synthetic strategies (recall assertable):")
        print("\n".join(f"  {s}" for s in _discover_strategies()))
        wild = corpora.wild_corpora()
        if wild:
            print("\nwild corpora (scoreboard only, costs LLM tokens — opt in by name):")
            for name, spec in sorted(wild.items()):
                staged = "staged" if _staged_wild(name) else "stageable"
                print(f"  {name}  [{spec.source} → vertical {spec.vertical}, {staged}]")
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
    unknown = [s for s in strategies if s not in known and not _is_wild_target(s)]
    if unknown:
        parser.error(f"unknown target"
                     f"{'s' if len(unknown) > 1 else ''}: {', '.join(unknown)} "
                     f"(not a strategy in strategies/, nor a wild corpus — see --list)")

    if args.bless_coverage:
        from calibration import coverage

        for strategy in strategies:
            ledger = _read_coverage(strategy).get("oracles")
            if not ledger:
                print(f"[bless] {strategy}: no oracle ledger at "
                      f"output/{strategy}/oracle_coverage.json — run its assert pass first")
                continue
            path = coverage.save_baseline(strategy, ledger)
            print(f"[bless] {strategy}: {len(coverage.graded_nodeids(ledger))} "
                  f"graded oracles -> {path.relative_to(runner.EVAL_ROOT)}")
        return

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
