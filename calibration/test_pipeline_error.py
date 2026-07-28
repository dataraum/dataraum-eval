"""The pipeline-error oracle — grade the ENGINE's answer path (DAT-687 / RFC 3 A3).

Every other oracle here grades what the engine *measured*. This one grades what it
*computed*: the metric SQL the graph agent composed and persisted, executed on the
run's own lake and compared to generator truth at KPI decision tolerance.

Four legs, deliberately separate because they fail for different reasons:

1. ``test_pipeline_error_within_kpi_tolerance`` — the like-for-like comparison. Only
   quantities whose population provably matches ground truth's are graded
   (``pipeline_error.PAIRS``); the rest are recorded with the reason they cannot be
   (``UNPAIRED``). A clean-data invariant, exactly like the golden-SQL leg: on an
   injected corpus the deviations ARE the injection, reported not graded.
2. ``test_declared_metric_expectations_hold`` — the engine against ITS OWN declared
   contract (each metric graph's ``validation: [{condition, severity}]``). No eval
   metric definition is involved, so a violation is unarguable and needs no pairing.
3. ``test_grounded_validations_pass_on_clean`` — leg (b) of the ticket: re-run each
   executed validation's stored ``sql_used`` and judge it with the engine's own rule.
   On clean data a failing grounded check is a false alarm, and this names it directly
   instead of waiting for the readiness fan-out it causes.
4. ``test_every_engine_quantity_is_graded_or_reasoned`` — the anti-vacuity leg. A
   number the engine computed that nobody paired and nobody explained is how this
   oracle would quietly stop measuring anything.

The values land in the verdict store through ``verdict_values`` (DAT-862 ext 1), so
the pipeline-error DISTRIBUTION is a store query rather than a log to re-read —
``python -m calibration.results_store -s clean --values pipeline_relative_error``.
That distribution is what makes every band in RFC 1 honest.
"""

from __future__ import annotations

import pytest

from calibration import cube, pipeline_error, verdict_values

pytestmark = cube.needs(
    vertical="finance", dataset="*", from_stage="operating_model", version=1
)


@pytest.fixture(scope="module")
def engine_quantities(strategy_name: str) -> list[pipeline_error.Quantity]:
    """The engine's own numbers, executed once per module (each is a lake query)."""
    from calibration.conftest import require_pipeline_run

    require_pipeline_run(strategy_name)
    return pipeline_error.engine_quantities(strategy_name)


@pytest.fixture(scope="module")
def report(
    strategy_name: str, engine_quantities: list[pipeline_error.Quantity]
) -> pipeline_error.Report:
    return pipeline_error.measure(strategy_name, quantities=engine_quantities)


def test_pipeline_error_within_kpi_tolerance(
    report: pipeline_error.Report,
    strategy_name: str,
    request: pytest.FixtureRequest,
) -> None:
    """The engine's own metric SQL reproduces generator truth at KPI tolerance.

    This is the pipeline-error term of ``pipeline error + model error ≤ decision
    tolerance``. Graded at the deliverable spec's tolerance, never at reporting
    exactness (DAT-681 policy (d)) — a KPI that is right to 1% is right.
    """
    print("\n" + pipeline_error.render(report))

    assert report.graded, (
        "nothing was graded — no engine quantity could be paired with ground truth. "
        "A pipeline-error measurement that measures nothing is worse than none: fix "
        "pipeline_error.PAIRS or the run, do not accept the green."
    )

    for row in report.graded:
        # Named `pipeline_*`, NOT `relative_error`: `test_ground_truth` records the
        # GOLDEN-SQL leg under that name, and the two measure different things — ours
        # is the engine's error, theirs is our own SQL's. One query
        # (`--values pipeline_relative_error`) must be the pipeline-error distribution
        # and nothing else, or RFC 1's bands cover a blend of the two.
        #
        # Relative error is the comparable unit across metrics of different magnitude
        # (RFC 1's open question, resolved here); the judging bar rides on whichever
        # form the deliverable spec declared, so `held` means what it says.
        subject = f"{row.engine}:{row.grounding_class}"
        if row.tolerance_abs is None:
            verdict_values.record(
                request, "pipeline_relative_error", row.relative_error_pct,
                threshold=row.tolerance_pct, comparator="<=",
                unit="percent", subject=subject,
            )
        else:
            # An absolute bar judges the absolute error; the relative form rides along
            # reported, so the distribution is comparable across metrics either way.
            verdict_values.record(
                request, "pipeline_relative_error", row.relative_error_pct,
                unit="percent", subject=subject,
            )
            verdict_values.record(
                request, "pipeline_absolute_error", row.absolute_error,
                threshold=row.tolerance_abs, comparator="<=",
                unit=row.unit, subject=subject,
            )

    if strategy_name != "clean":
        pytest.skip(
            f"pipeline-error reproduction is a clean-data invariant; on injected "
            f"'{strategy_name}' the deviations above are the injection, reported not graded"
        )

    off = [r for r in report.graded if not r.in_tolerance]
    assert not off, (
        "the engine's own metric SQL does not reproduce ground truth on CLEAN data at "
        "KPI tolerance — this is pipeline error, the term every band in the forecast "
        "story has to cover:\n  "
        + "\n  ".join(
            f"{r.engine} [{r.grounding_class}]: computed {r.computed:,.2f} vs expected "
            f"{r.expected:,.2f} (rel {r.relative_error_pct:.4f}%, tol "
            f"{r.tolerance_abs if r.tolerance_abs is not None else r.tolerance_pct})"
            for r in off
        )
    )


def test_declared_metric_expectations_hold(
    strategy_name: str,
    engine_quantities: list[pipeline_error.Quantity],
    request: pytest.FixtureRequest,
) -> None:
    """Every executed metric satisfies the condition its OWN graph declares.

    The strongest available leg, because it borrows no definition from us: the metric
    graph ships ``validation: [{condition: 0 <= value <= 365, severity: …}]`` and the
    phase transitions the artifact to ``executed``. A violated condition on CLEAN data
    is the engine disagreeing with itself.

    Reported per severity. Whether a violated *warning* should block the lifecycle
    transition is the engine team's call — we grade that the condition is violated,
    not what the state machine ought to do about it.
    """
    expectations = pipeline_error.declared_expectations(
        strategy_name, quantities=engine_quantities
    )
    if not expectations:
        pytest.skip("no executed metric declares a validation condition in its graph")

    checked = [e for e in expectations if e.holds is not None]
    unparseable = [e for e in expectations if e.holds is None]
    print(f"\n[declared expectations] {len(checked)} checked, {len(unparseable)} unparseable:")
    for e in expectations:
        mark = {True: "ok ", False: "VIOLATED", None: " ?? "}[e.holds]
        shown = "—" if e.value is None else f"{e.value:,.4f}"
        print(f"  [{mark}] {e.metric:<20} {e.condition:<22} value={shown:<18} {e.severity}")

    violated = [e for e in checked if not e.holds]
    verdict_values.record(
        request, "declared_expectation_violations", len(violated),
        threshold=0, comparator="==", unit="count",
    )
    verdict_values.record(request, "declared_expectations_checked", len(checked), unit="count")

    assert checked, (
        "no declared condition could be evaluated — every one was unparseable, so this "
        f"leg graded nothing: {[e.condition for e in unparseable]}"
    )
    assert not violated, (
        "executed metric(s) violate the condition their own graph declares:\n  "
        + "\n  ".join(
            f"{e.metric}: {e.condition} but value = {e.value:,.4f} "
            f"(severity {e.severity!r}: {e.message})"
            for e in violated
        )
    )


def test_grounded_validations_pass_on_clean(
    strategy_name: str, request: pytest.FixtureRequest
) -> None:
    """DAT-687 leg (b): every EXECUTED validation's recomputed verdict passes on clean.

    Verdicts are recomputed-not-stored (ADR-0017), so this re-runs each check's stored
    ``sql_used`` and judges it with the engine's OWN rule
    (``validation.evaluate.verdict_from_sql``) — not a reimplementation, which would
    drift from theirs the first time the per-leg semantics move.

    On clean data a grounded check that fails is a **false alarm**: nothing is wrong
    with the data, so the check itself is wrong. That is a more direct signal than the
    readiness/band fan-out it eventually causes, and it names the offending check.

    Checks the engine DECLINED to execute are reported, never counted as failures —
    an artifact left at ``declared`` with a binder error is the abstention contract
    working. Counting those would fabricate findings out of correct refusals.
    """
    verdicts, abstained = pipeline_error.validation_verdicts(strategy_name)
    if not verdicts:
        pytest.skip("no executed validation carries stored SQL for this run")

    print("\n" + pipeline_error.render_verdicts(verdicts, abstained))

    failed = [v for v in verdicts if v.status == "failed"]
    errored = [v for v in verdicts if v.status == "error"]
    # The bar is only declared where it applies: on an injected corpus a failing check
    # may be the injection being caught, so zero failures is not the criterion there.
    if strategy_name == "clean":
        verdict_values.record(
            request, "validation_failures_on_clean", len(failed),
            threshold=0, comparator="==", unit="count",
        )
    else:
        verdict_values.record(
            request, "validation_failures_on_clean", len(failed), unit="count",
        )
    verdict_values.record(request, "validations_executed", len(verdicts), unit="count")
    verdict_values.record(request, "validations_abstained", len(abstained), unit="count")
    verdict_values.record(request, "validations_inconclusive", len(errored), unit="count")

    if strategy_name != "clean":
        pytest.skip(
            f"grounded checks passing is a clean-data invariant; on injected "
            f"'{strategy_name}' a failing check may be the injection being caught"
        )

    assert not failed, (
        "generated validation(s) FAIL on clean data — the data is fine, so the check is "
        "wrong (a false alarm that fans out into readiness bands):\n  "
        + "\n  ".join(
            f"{v.name} [{v.check_type}, {v.severity}]: {v.message}" for v in failed
        )
    )


def test_every_engine_quantity_is_graded_or_reasoned(
    report: pipeline_error.Report, request: pytest.FixtureRequest
) -> None:
    """No engine number is silently ungraded — the anti-vacuity leg.

    The failure mode this oracle would drift into is comfortable: the engine grows a
    metric, nobody pairs it, and the pipeline-error distribution keeps reporting the
    same three green quantities forever. An unpaired quantity must carry a stated
    reason (``pipeline_error.UNPAIRED``), the same discipline as a skipped oracle's
    reason — so the ungraded surface is visible and shrinkable, never invisible.
    """
    unexplained = sorted(
        name for name, reason in report.unpaired.items()
        if reason.startswith("not paired and no reason recorded")
    )
    verdict_values.record(
        request, "ungraded_engine_quantities", len(report.unpaired), unit="count",
    )
    verdict_values.record(
        request, "unexplained_engine_quantities", len(unexplained),
        threshold=0, comparator="==", unit="count",
    )
    assert not unexplained, (
        "the engine computed quantities that are neither graded nor explained — declare "
        "each in pipeline_error.PAIRS (with why the populations match) or UNPAIRED (with "
        f"why they cannot be compared): {unexplained}"
    )
