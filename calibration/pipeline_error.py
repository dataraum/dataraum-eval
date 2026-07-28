"""The pipeline-error term — grade the ENGINE's own answer path (DAT-687 / RFC 3 A3).

`pipeline error + model error ≤ decision tolerance` is the product's grading
contract. The model term is decided (CQR, DAT-750). The pipeline term — the error
the model *recovery* introduces before any prediction: wrong grounding, wrong sign
convention, an unbound period axis, a stock summed across periods — was unmeasured,
and until it exists, deviation significance and a *lit* coverage map are claims
rather than properties.

``calibration/outcomes.py`` grades EVAL's own golden SQL. This grades the ENGINE's:
the per-metric formula SQL the metrics phase composed and persisted in
``sql_snippets`` (DAT-646), plus the level-1 extract snippets underneath it
(``current_groundings``, DAT-727), executed on the run's own lake and compared to
``ground_truth.yaml`` at **KPI decision tolerance, never reporting exactness**
(DAT-681 policy (d)).

**Like-for-like or not at all.** The engine's ``gross_profit`` is revenue − COGS;
our ground truth's is revenue − *all* expenses. Comparing them yields a 77% "error"
that is entirely our own definition, and filing that against the engine would be
exactly the rumour-spreading the charter forbids. So a quantity is graded only when
both sides demonstrably measure the same population (:data:`PAIRS`), and every
ungraded one is recorded with the reason it cannot be paired (:data:`UNPAIRED`) —
a run must never look accurate by comparing nothing.

**Attribution is by grounding class**, which RFC 1 leaves open and the data settles:
an extract either predicates on a TYPED semantic column (``account_type``) or
enumerates account NAMES, and a formula is DERIVED from whatever its extracts did.
Reporting error per class says *what kind of recovery* was uncertain, rather than
blaming "the pipeline" as a lump.

    uv run python -m calibration.pipeline_error -s clean
    uv run python -m calibration.pipeline_error -s clean --expectations
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EVAL_ROOT = Path(__file__).parent.parent

# Grounding classes — how the recovered SQL selected its population.
TYPED = "typed_predicate"  # predicates on account_id__account_type: a semantic type
NAMED = "name_enumeration"  # enumerates account_id__name literals: a string list
MIXED = "mixed"
DERIVED = "derived"  # a formula over extracts — inherits their classes
UNKNOWN = "unknown"  # pre-parts snippet: no clause parts to read


@dataclass(frozen=True)
class Quantity:
    """One engine-computed number, with how it was recovered."""

    name: str  # graph_id for a metric, concept for an extract
    kind: str  # metric | extract
    value: float | None  # None when the SQL failed or returned NULL
    grounding_class: str
    error: str = ""  # the execution failure, when value is None
    relation: str = ""  # the FROM relation an extract resolved to
    predicates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Pairing:
    """An engine quantity paired with a ground-truth key, or explicitly not.

    ``tolerance_pct`` / ``tolerance_abs`` mirror the deliverable-spec grammar:
    exactly one is set, and it is the KPI decision tolerance, not exactness.
    ``why`` states what makes the two sides the same population — the sentence that
    has to be true for the comparison to mean anything.
    """

    engine: str
    truth_key: str
    unit: str  # currency | days | ratio
    tolerance_pct: float | None = None
    tolerance_abs: float | None = None
    why: str = ""


# Graded pairs — both sides measure the same population, verified on `clean`.
PAIRS: tuple[Pairing, ...] = (
    Pairing(
        engine="revenue", truth_key="total_revenue", unit="currency", tolerance_pct=1.0,
        why="engine sums credit−debit over account_type='revenue'; truth sums credit over "
            "account_id LIKE '4%' — the same accounts, and revenue accounts carry no debits "
            "on clean data (verified identical to the cent)",
    ),
    Pairing(
        engine="accounts_receivable", truth_key="ending_ar_balance", unit="currency",
        tolerance_pct=1.0,
        why="engine sums balance-sheet ending_balance over the receivable account names; "
            "truth sums debit−credit over accounts 1210/1220 — the generator's balance sheet "
            "is cumulative and reconciles with its own GL for asset-natural accounts",
    ),
    Pairing(
        engine="dso", truth_key="annual_dso", unit="days", tolerance_abs=3.0,
        why="both are (accounts_receivable / revenue) × days_in_period, and the engine's "
            "period_grain derivation resolved days_in_period to the fiscal year",
    ),
)

# Deliberately NOT graded — with the reason. An unpaired quantity is coverage
# evidence, exactly like a skipped oracle: it says "this number exists and nobody
# checked it", which is the thing a green run must never hide.
UNPAIRED: dict[str, str] = {
    "gross_profit":
        "definition differs: engine = revenue − cost_of_goods_sold (1.78M of COGS); "
        "our ground truth = revenue − ALL expenses (23.5M). Two different metrics wearing "
        "one name — comparing them would blame the engine for our definition. Resolve the "
        "naming before grading (the eval-side key is the misnamed one: revenue − all "
        "expenses is operating income, not gross profit)",
    "accounts_payable":
        "scope differs: truth's AP = {2110 Trade Payables, 2120 Accrued Expenses}; the "
        "engine's extract enumerates ('Accounts Payable','Trade Payables') and misses "
        "Accrued Expenses (2,141,863.57 of the 3,745,513.61 gap). The window and sign "
        "defects inside this extract are filed separately with their own repro — they are "
        "provable WITHOUT resolving the scope question",
    "dpo":
        "inherits accounts_payable's scope divergence, so the value cannot be attributed "
        "to the engine. Its declared-expectation violation (−124.73 days against the "
        "graph's own 0 ≤ value ≤ 365) is graded by "
        "`test_declared_metric_expectations_hold` instead, which needs no eval definition",
    "current_ratio": "no ground-truth counterpart (the generator exports no current-ratio truth)",
    "ebitda": "no ground-truth counterpart",
    "ebitda_margin": "no ground-truth counterpart",
    "gross_margin": "no ground-truth counterpart, and inherits gross_profit's definition split",
    "net_income": "no ground-truth counterpart",
    "net_margin": "no ground-truth counterpart",
    "operating_income": "no ground-truth counterpart",
    "operating_margin": "no ground-truth counterpart",
    "active_accounts": "no ground-truth counterpart (a count, not a financial value)",
    "transaction_count": "no ground-truth counterpart (a count, not a financial value)",
    "average_transaction_value": "no ground-truth counterpart",
    "transaction_amount": "extract behind the count/avg metrics; no truth counterpart",
    "account": "extract behind active_accounts; no truth counterpart",
    "cost_of_goods_sold": "no ground-truth counterpart (truth exports total expenses, not COGS)",
    "operating_expense": "no ground-truth counterpart (a subset of truth's total_expenses)",
    "depreciation": "no ground-truth counterpart",
    "interest": "no ground-truth counterpart",
    "tax": "no ground-truth counterpart (truth exports no tax line)",
    "inventory": "the generator has no inventory; the extract is a retained FAILED snippet and "
                 "the metrics that need it correctly stayed `grounded` — the abstention "
                 "contract working, not an error",
    "current_assets": "no ground-truth counterpart",
    "current_liabilities": "no ground-truth counterpart",
}


@dataclass(frozen=True)
class ErrorRow:
    """One graded quantity's pipeline error."""

    engine: str
    truth_key: str
    unit: str
    grounding_class: str
    computed: float
    expected: float
    relative_error_pct: float
    absolute_error: float
    tolerance_pct: float | None
    tolerance_abs: float | None

    @property
    def in_tolerance(self) -> bool:
        if self.tolerance_abs is not None:
            return self.absolute_error <= self.tolerance_abs
        pct = 1.0 if self.tolerance_pct is None else self.tolerance_pct
        return self.relative_error_pct <= pct

    @property
    def threshold(self) -> float:
        """The bar this row was judged at, in its own error unit."""
        return self.tolerance_abs if self.tolerance_abs is not None else (self.tolerance_pct or 1.0)

    @property
    def error(self) -> float:
        """The error the threshold judges — absolute for an abs bar, relative for a pct one."""
        return self.absolute_error if self.tolerance_abs is not None else self.relative_error_pct


@dataclass
class Report:
    strategy: str
    quantities: list[Quantity] = field(default_factory=list)
    graded: list[ErrorRow] = field(default_factory=list)
    unpaired: dict[str, str] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)

    @property
    def distribution(self) -> dict[str, Any]:
        """The pipeline-error distribution — the number RFC 1's bands must cover.

        Relative error in percent over every graded quantity, plus the per-
        grounding-class split so a band is attributable to a KIND of recovery.
        """
        errs = sorted(r.relative_error_pct for r in self.graded)
        by_class: dict[str, list[float]] = {}
        for r in self.graded:
            by_class.setdefault(r.grounding_class, []).append(r.relative_error_pct)
        return {
            "n": len(errs),
            "min_pct": errs[0] if errs else None,
            "median_pct": errs[len(errs) // 2] if errs else None,
            "max_pct": errs[-1] if errs else None,
            "out_of_tolerance": [r.engine for r in self.graded if not r.in_tolerance],
            "by_grounding_class": {
                cls: {"n": len(vals), "max_pct": max(vals)} for cls, vals in sorted(by_class.items())
            },
        }


# ---------------------------------------------------------------------------
# Reading the engine's persisted answer path
# ---------------------------------------------------------------------------


def _classify(predicates: list[str]) -> str:
    """Which recovery kind selected this extract's population (pure)."""
    typed = any("account_id__account_type" in p for p in predicates)
    named = any("account_id__name" in p for p in predicates)
    if typed and named:
        return MIXED
    if typed:
        return TYPED
    if named:
        return NAMED
    return UNKNOWN


def _predicates(where_predicates: str | None) -> list[str]:
    if not where_predicates:
        return []
    try:
        loaded = json.loads(where_predicates)
    except ValueError:
        return []
    return [str(p) for p in loaded] if isinstance(loaded, list) else []


def _snippets(strategy: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(formulas, extracts)`` the run persisted — read-only, no pipeline."""
    from sqlalchemy import text

    from calibration.tools._runs import load_run, workspace_session

    load_run(strategy)
    with workspace_session() as session:
        from dataraum.storage.read_views import read_schema_name_for

        read_schema = read_schema_name_for(
            session.execute(text("SELECT current_schema()")).scalar()
        )
        formulas = [
            {"name": r.source.removeprefix("graph:"), "sql": r.sql}
            for r in session.execute(text(
                "SELECT source, sql FROM sql_snippets "
                "WHERE snippet_type = 'formula' AND source LIKE 'graph:%' ORDER BY source"
            )).all()
        ]
        extracts = [
            {
                "name": r.concept,
                "sql": r.sql,
                "relation": r.relation or "",
                "predicates": _predicates(r.where_predicates),
                "failed": bool(r.failed),
            }
            for r in session.execute(text(
                f'SELECT concept, sql, relation, where_predicates, failed '
                f'FROM "{read_schema}".current_groundings ORDER BY concept'
            )).all()
        ]
    return formulas, extracts


def engine_quantities(strategy: str) -> list[Quantity]:
    """Execute the engine's own persisted SQL on the run's lake.

    A snippet that raises is a Quantity with ``value=None`` and the error text — the
    failure is data, never a swallowed exception: a metric whose SQL no longer runs
    is a bigger finding than one whose number is off.
    """
    from calibration import runner as runner_mod

    formulas, extracts = _snippets(strategy)
    runner_mod.bootstrap_engine()
    from dataraum.worker.bootstrap import bootstrap_worker_substrate, shutdown_worker_substrate

    out: list[Quantity] = []
    manager = bootstrap_worker_substrate()
    try:
        with manager.duckdb_cursor() as cursor:

            def run_one(sql: str) -> tuple[float | None, str]:
                try:
                    cursor.execute(sql)
                    row = cursor.fetchone()
                except Exception as exc:  # noqa: BLE001 — the failure IS the measurement
                    return None, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
                if row is None or row[0] is None:
                    return None, "SQL returned NULL"
                return float(row[0]), ""

            for e in extracts:
                value, err = run_one(e["sql"])
                out.append(Quantity(
                    name=e["name"], kind="extract", value=value,
                    grounding_class=_classify(e["predicates"]),
                    error=err or ("retained FAILED snippet" if e["failed"] else ""),
                    relation=e["relation"], predicates=tuple(e["predicates"]),
                ))
            for f in formulas:
                value, err = run_one(f["sql"])
                out.append(Quantity(
                    name=f["name"], kind="metric", value=value,
                    grounding_class=DERIVED, error=err,
                ))
    finally:
        shutdown_worker_substrate(manager)
    return out


def _ground_truth(strategy: str) -> dict[str, Any]:
    path = EVAL_ROOT / "data" / strategy / "ground_truth.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no ground truth at {path} — generate the strategy first")
    loaded: dict[str, Any] = yaml.safe_load(path.read_text())
    annual: dict[str, Any] = loaded.get("annual", {}) or {}
    return annual


def measure(
    strategy: str,
    *,
    quantities: list[Quantity] | None = None,
    truth: dict[str, Any] | None = None,
) -> Report:
    """The pipeline-error report for one completed run.

    ``quantities`` / ``truth`` override the two I/O reads (the lake and the
    generator's ``ground_truth.yaml``) — the Tier-1 seam, so the pairing rules and
    the distribution are proven in milliseconds without a pipeline or a corpus.
    """
    quantities = engine_quantities(strategy) if quantities is None else quantities
    truth = _ground_truth(strategy) if truth is None else truth
    report = Report(strategy=strategy, quantities=quantities)

    by_name: dict[str, Quantity] = {}
    for q in quantities:
        # Several extracts can share a concept (transaction_amount at two aggregations);
        # a metric of the same name wins, since it is the graded surface.
        if q.name not in by_name or q.kind == "metric":
            by_name[q.name] = q

    for pair in PAIRS:
        q = by_name.get(pair.engine)
        if q is None:
            report.unavailable[pair.engine] = "the run persisted no such metric/extract"
            continue
        if q.value is None:
            report.unavailable[pair.engine] = q.error or "no value"
            continue
        if pair.truth_key not in truth:
            report.unavailable[pair.engine] = (
                f"ground truth has no {pair.truth_key!r} for {strategy}"
            )
            continue
        expected = float(truth[pair.truth_key])
        absolute = abs(q.value - expected)
        relative = absolute / abs(expected) * 100.0 if expected else float("inf")
        report.graded.append(ErrorRow(
            engine=pair.engine, truth_key=pair.truth_key, unit=pair.unit,
            grounding_class=q.grounding_class, computed=q.value, expected=expected,
            relative_error_pct=relative, absolute_error=absolute,
            tolerance_pct=pair.tolerance_pct, tolerance_abs=pair.tolerance_abs,
        ))

    graded_names = {p.engine for p in PAIRS}
    for q in quantities:
        if q.name in graded_names:
            continue
        reason = UNPAIRED.get(q.name, "not paired and no reason recorded — declare it in UNPAIRED")
        report.unpaired[q.name] = reason
    return report


# ---------------------------------------------------------------------------
# The engine's own declared expectations (no eval definition involved)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Expectation:
    """A metric graph's own declared condition, checked against its own value."""

    metric: str
    condition: str
    severity: str
    message: str
    value: float | None
    holds: bool | None  # None = unparseable condition or no value


def _condition_holds(condition: str, value: float) -> bool | None:
    """Evaluate a declared condition of the form ``0 <= value <= 365`` (pure, safe).

    Parsed with ``ast`` over a whitelist — a chained comparison of ``value`` against
    numeric literals. Anything else returns ``None`` (unparseable), never a guess and
    never ``eval``: the conditions come from config the engine team edits.
    """
    try:
        tree = ast.parse(condition.strip(), mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(tree, ast.Compare):
        return None
    ops = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!="}

    def operand(node: ast.expr) -> float | None:
        if isinstance(node, ast.Name) and node.id == "value":
            return value
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = operand(node.operand)
            return None if inner is None else -inner
        return None

    left = operand(tree.left)
    if left is None:
        return None
    for op, comparator in zip(tree.ops, tree.comparators, strict=True):
        right = operand(comparator)
        symbol = ops.get(type(op))
        if right is None or symbol is None:
            return None
        held = {
            "<": left < right, "<=": left <= right, ">": left > right,
            ">=": left >= right, "==": left == right, "!=": left != right,
        }[symbol]
        if not held:
            return False
        left = right
    return True


def declared_expectations(
    strategy: str, *, quantities: list[Quantity] | None = None
) -> list[Expectation]:
    """Every executed metric's declared validation, checked against its own value.

    This grades the engine against the contract IT declares in its own metric graphs
    (``validation: [{condition, severity, message}]``) — no eval metric definition is
    involved, so a violation is unarguable and needs no like-for-like pairing. The
    declared ``severity`` rides along: whether a violated *warning* should block the
    lifecycle transition is the engine team's call; that it is violated on CLEAN data
    is the finding.
    """
    from sqlalchemy import text

    from calibration.tools._runs import load_run, workspace_session

    load_run(strategy)
    with workspace_session() as session:
        from dataraum.storage.read_views import read_schema_name_for

        read_schema = read_schema_name_for(
            session.execute(text("SELECT current_schema()")).scalar()
        )
        rows = session.execute(text(
            f'SELECT artifact_key, state, graph_definition '
            f'FROM "{read_schema}".current_lifecycle_artifacts '
            f"WHERE artifact_type = 'metric' AND state = 'executed' ORDER BY artifact_key"
        )).all()

    values = {
        q.name: q.value
        for q in (engine_quantities(strategy) if quantities is None else quantities)
        if q.kind == "metric"
    }

    out: list[Expectation] = []
    for row in rows:
        defn = row.graph_definition or {}
        if isinstance(defn, str):
            defn = json.loads(defn)
        value = values.get(row.artifact_key)
        for step in (defn.get("dependencies") or {}).values():
            if not isinstance(step, dict) or not step.get("output_step"):
                continue
            for check in step.get("validation") or []:
                condition = str(check.get("condition", ""))
                out.append(Expectation(
                    metric=row.artifact_key,
                    condition=condition,
                    severity=str(check.get("severity", "")),
                    message=str(check.get("message", "")),
                    value=value,
                    holds=None if value is None else _condition_holds(condition, value),
                ))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def render(report: Report) -> str:
    lines = [f"pipeline error — {report.strategy} (the ENGINE's own metric SQL vs generator truth)"]
    lines.append("")
    if not report.graded:
        lines.append("  NOTHING GRADED — no engine quantity could be paired like-for-like")
    for r in sorted(report.graded, key=lambda r: -r.error):
        flag = "ok " if r.in_tolerance else "OFF"
        bar = f"{r.tolerance_abs} abs" if r.tolerance_abs is not None else f"{r.tolerance_pct}%"
        lines.append(
            f"  [{flag}] {r.engine:<22} computed={r.computed:>18,.4f} "
            f"expected={r.expected:>18,.4f}  rel={r.relative_error_pct:>8.4f}%  "
            f"tol={bar:<9} [{r.grounding_class}]"
        )
    dist = report.distribution
    lines.append("")
    fmt = lambda v: "—" if v is None else f"{v:.4g}%"  # noqa: E731 — local formatter
    lines.append(f"  distribution over {dist['n']} graded: min={fmt(dist['min_pct'])} "
                 f"median={fmt(dist['median_pct'])} max={fmt(dist['max_pct'])}")
    for cls, stats in dist["by_grounding_class"].items():
        lines.append(f"    {cls:<18} n={stats['n']}  max={stats['max_pct']:.4f}%")
    if dist["out_of_tolerance"]:
        lines.append(f"  OUT OF TOLERANCE: {', '.join(dist['out_of_tolerance'])}")

    failed = [q for q in report.quantities if q.value is None]
    if failed:
        lines.append("")
        lines.append(f"  quantities with no value ({len(failed)}):")
        for q in failed:
            lines.append(f"    {q.name:<24} {q.error}")

    lines.append("")
    lines.append(f"  ungraded, with reason ({len(report.unpaired)}) — coverage evidence, not a pass:")
    for name, reason in sorted(report.unpaired.items()):
        lines.append(f"    {name:<24} {reason[:110]}")
    if report.unavailable:
        lines.append("")
        lines.append("  declared pairs the run could not supply:")
        for name, reason in sorted(report.unavailable.items()):
            lines.append(f"    {name:<24} {reason}")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="pipeline-error measurement (DAT-687)")
    parser.add_argument("-s", "--strategy", default="clean")
    parser.add_argument("--expectations", action="store_true",
                        help="check each executed metric against its graph's own declared "
                             "validation conditions")
    args = parser.parse_args()

    quantities = engine_quantities(args.strategy)
    print(render(measure(args.strategy, quantities=quantities)))

    if args.expectations:
        print("\ndeclared metric expectations (the engine's own contract):")
        for e in declared_expectations(args.strategy, quantities=quantities):
            mark = {True: "ok ", False: "VIOLATED", None: " · "}[e.holds]
            shown = "—" if e.value is None else f"{e.value:,.4f}"
            print(f"  [{mark}] {e.metric:<20} {e.condition:<22} value={shown:<18} "
                  f"severity={e.severity}")


if __name__ == "__main__":
    main()
